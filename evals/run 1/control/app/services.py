from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import EmailProviderClient, PaymentProviderClient
from app.errors import ApplicationError, ExternalProviderError
from app.models import (
    Customer,
    Event,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    PaymentAttempt,
    PaymentAttemptStatus,
    utc_now,
)
from app.schemas import (
    CustomerCreate,
    CustomerRead,
    InvoiceCreate,
    InvoiceLineCreate,
    InvoiceRead,
    InvoiceTotals,
    PaymentAttemptCreate,
    PaymentAttemptRead,
)
from app.totals import calculate_totals, invoice_to_read


class InvoiceCollectionService:
    def __init__(
        self,
        session: AsyncSession,
        payment_provider: PaymentProviderClient,
        email_provider: EmailProviderClient,
    ) -> None:
        self._session = session
        self._payment_provider = payment_provider
        self._email_provider = email_provider

    async def create_customer(self, payload: CustomerCreate) -> CustomerRead:
        customer = Customer(name=payload.name, email=str(payload.email))
        self._session.add(customer)
        await self._session.commit()
        return CustomerRead.model_validate(customer)

    async def create_invoice(
        self, customer_id: uuid.UUID, payload: InvoiceCreate | None = None
    ) -> InvoiceRead:
        del payload
        customer = await self._session.get(Customer, customer_id)
        if customer is None:
            raise ApplicationError("customer_not_found", "Customer was not found.", 404)

        invoice = Invoice(customer_id=customer_id, status=InvoiceStatus.DRAFT)
        self._session.add(invoice)
        await self._session.commit()
        return await self.get_invoice(invoice.id)

    async def get_invoice(self, invoice_id: uuid.UUID) -> InvoiceRead:
        invoice = await self._load_invoice(invoice_id)
        return invoice_to_read(invoice)

    async def calculate_invoice_total(self, invoice_id: uuid.UUID) -> InvoiceTotals:
        invoice = await self._load_invoice(invoice_id)
        return calculate_totals(invoice.lines)

    async def add_invoice_line(
        self, invoice_id: uuid.UUID, payload: InvoiceLineCreate
    ) -> InvoiceRead:
        invoice = await self._load_invoice(invoice_id)
        if invoice.status != InvoiceStatus.DRAFT:
            raise ApplicationError(
                "invoice_not_draft",
                "Line items can only be added while the invoice is draft.",
                409,
            )

        line = InvoiceLine(
            invoice_id=invoice.id,
            description=payload.description,
            quantity=payload.quantity,
            unit_price=payload.unit_price,
            tax_rate=payload.tax_rate,
        )
        self._session.add(line)
        await self._session.commit()
        return await self.get_invoice(invoice.id)

    async def issue_invoice(self, invoice_id: uuid.UUID) -> InvoiceRead:
        invoice = await self._load_invoice(invoice_id)
        if invoice.status != InvoiceStatus.DRAFT:
            raise ApplicationError(
                "invoice_not_draft",
                "Only draft invoices can be issued.",
                409,
            )
        if not invoice.lines:
            raise ApplicationError(
                "empty_invoice",
                "An empty invoice cannot be issued.",
                409,
            )

        totals = calculate_totals(invoice.lines)
        try:
            await self._email_provider.send_invoice_issued(
                invoice_id=invoice.id,
                customer_id=invoice.customer_id,
                total=totals.total,
            )
        except ExternalProviderError as exc:
            raise ApplicationError(
                "email_provider_error",
                f"Could not send issued invoice email: {exc.message}",
                502,
            ) from exc

        invoice.status = InvoiceStatus.ISSUED
        invoice.issued_at = utc_now()
        self._session.add(
            Event(
                type="invoice.issued",
                aggregate_id=invoice.id,
                payload={
                    "invoice_id": str(invoice.id),
                    "customer_id": str(invoice.customer_id),
                    "total": str(totals.total),
                },
            )
        )
        await self._session.commit()
        return await self.get_invoice(invoice.id)

    async def collect_payment(
        self,
        invoice_id: uuid.UUID,
        payload: PaymentAttemptCreate,
        idempotency_key: str,
    ) -> PaymentAttemptRead:
        invoice = await self._load_invoice(invoice_id)
        existing_attempt = await self._get_payment_attempt(invoice_id, idempotency_key)
        if existing_attempt is not None:
            return self._payment_attempt_to_read(existing_attempt, invoice.status)

        if invoice.status == InvoiceStatus.PAID:
            raise ApplicationError(
                "invoice_already_paid",
                "A paid invoice cannot be paid again.",
                409,
            )
        if invoice.status != InvoiceStatus.ISSUED:
            raise ApplicationError(
                "invoice_not_issued",
                "Payment can only be collected for issued invoices.",
                409,
            )

        totals = calculate_totals(invoice.lines)
        attempt = PaymentAttempt(
            invoice_id=invoice.id,
            idempotency_key=idempotency_key,
            status=PaymentAttemptStatus.PROCESSING,
            amount=totals.total,
        )
        self._session.add(attempt)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing_attempt = await self._get_payment_attempt(invoice_id, idempotency_key)
            if existing_attempt is None:
                raise
            return self._payment_attempt_to_read(existing_attempt, invoice.status)

        try:
            result = await self._payment_provider.collect_payment(
                invoice_id=invoice.id,
                amount=totals.total,
                payment_method_token=payload.payment_method_token,
                idempotency_key=idempotency_key,
            )
        except ExternalProviderError as exc:
            attempt.status = PaymentAttemptStatus.FAILED
            attempt.error_code = "payment_provider_error"
            attempt.error_message = exc.message
            await self._session.commit()
            raise ApplicationError(
                "payment_provider_error",
                f"Could not collect payment: {exc.message}",
                502,
            ) from exc

        attempt.status = result.status
        attempt.provider_payment_id = result.provider_payment_id
        attempt.error_code = result.error_code
        attempt.error_message = result.error_message

        if result.status == PaymentAttemptStatus.SUCCEEDED:
            invoice.status = InvoiceStatus.PAID
            invoice.paid_at = utc_now()
            self._session.add(
                Event(
                    type="invoice.paid",
                    aggregate_id=invoice.id,
                    payload={
                        "invoice_id": str(invoice.id),
                        "payment_attempt_id": str(attempt.id),
                        "total": str(totals.total),
                    },
                )
            )

        await self._session.commit()
        return self._payment_attempt_to_read(attempt, invoice.status)

    async def _load_invoice(self, invoice_id: uuid.UUID) -> Invoice:
        statement = (
            select(Invoice)
            .options(selectinload(Invoice.lines))
            .where(Invoice.id == invoice_id)
            .execution_options(populate_existing=True)
        )
        invoice = await self._session.scalar(statement)
        if invoice is None:
            raise ApplicationError("invoice_not_found", "Invoice was not found.", 404)
        return invoice

    async def _get_payment_attempt(
        self, invoice_id: uuid.UUID, idempotency_key: str
    ) -> PaymentAttempt | None:
        statement = select(PaymentAttempt).where(
            PaymentAttempt.invoice_id == invoice_id,
            PaymentAttempt.idempotency_key == idempotency_key,
        )
        return await self._session.scalar(statement)

    def _payment_attempt_to_read(
        self, attempt: PaymentAttempt, invoice_status: InvoiceStatus
    ) -> PaymentAttemptRead:
        return PaymentAttemptRead(
            id=attempt.id,
            invoice_id=attempt.invoice_id,
            idempotency_key=attempt.idempotency_key,
            status=attempt.status,
            amount=attempt.amount,
            provider_payment_id=attempt.provider_payment_id,
            error_code=attempt.error_code,
            error_message=attempt.error_message,
            created_at=attempt.created_at,
            invoice_status=invoice_status,
        )
