from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.payment import PaymentProviderClient, PaymentProviderException
from app.events.invoice import InvoiceIssued, InvoicePaid
from app.outbox.repo import OutboxRepo
from app.repos.customer import CustomerRepo
from app.repos.invoice import InvoiceRepo
from app.schemas.customer import CustomerCreate, CustomerGet
from app.schemas.invoice import (
    AddInvoiceLineCommand,
    CollectPaymentCommand,
    InvoiceCreate,
    InvoiceGet,
    InvoiceTotalGet,
    PaymentCollectionGet,
)


class BillingService:
    def __init__(
        self,
        *,
        customers: CustomerRepo,
        invoices: InvoiceRepo,
        outbox: OutboxRepo,
        payment_provider: PaymentProviderClient,
        session: AsyncSession,
    ) -> None:
        self._customers = customers
        self._invoices = invoices
        self._outbox = outbox
        self._payment_provider = payment_provider
        self._session = session

    async def create_customer(self, cmd: CustomerCreate) -> CustomerGet:
        async with self._session.begin():
            customer = cmd.to_new_customer()
            await self._customers.add(customer)
        return CustomerGet.from_model(customer)

    async def create_invoice(self, cmd: InvoiceCreate) -> InvoiceGet:
        async with self._session.begin():
            await self._customers.get_or_raise(cmd.customer_id)
            invoice = cmd.to_new_invoice()
            await self._invoices.add(invoice)
        return InvoiceGet.from_model(invoice)

    async def add_invoice_line(self, invoice_id: UUID, cmd: AddInvoiceLineCommand) -> InvoiceGet:
        async with self._session.begin():
            invoice = await self._invoices.get_or_raise(invoice_id)
            invoice.add_line(
                description=cmd.description,
                quantity=cmd.quantity,
                unit_price=cmd.unit_price,
                tax_rate=cmd.tax_rate,
            )
        return InvoiceGet.from_model(invoice)

    async def get_invoice_total(self, invoice_id: UUID) -> InvoiceTotalGet:
        invoice = await self._invoices.get_or_raise(invoice_id)
        return InvoiceTotalGet.from_model(invoice)

    async def get_invoice(self, invoice_id: UUID) -> InvoiceGet:
        invoice = await self._invoices.get_or_raise(invoice_id)
        return InvoiceGet.from_model(invoice)

    async def issue_invoice(self, invoice_id: UUID) -> InvoiceGet:
        async with self._session.begin():
            invoice = await self._invoices.get_or_raise(invoice_id)
            invoice.issue()
            await self._outbox.add_event(InvoiceIssued.from_model(invoice))
        return InvoiceGet.from_model(invoice)

    async def collect_payment(
        self,
        invoice_id: UUID,
        cmd: CollectPaymentCommand,
    ) -> PaymentCollectionGet:
        async with self._session.begin():
            invoice = await self._invoices.get_or_raise(invoice_id)
            existing = await self._invoices.get_payment_attempt_by_idempotency_key(
                invoice_id=invoice_id,
                idempotency_key=cmd.idempotency_key,
            )
            if existing is not None:
                return PaymentCollectionGet.from_models(invoice=invoice, attempt=existing)

            attempt = invoice.start_payment_attempt(idempotency_key=cmd.idempotency_key)
            await self._invoices.add_payment_attempt(attempt)

        try:
            provider_result = await self._payment_provider.collect_payment(
                invoice_id=invoice_id,
                amount=attempt.amount,
                currency=attempt.currency,
                payment_method_token=cmd.payment_method_token,
                idempotency_key=cmd.idempotency_key,
            )
        except PaymentProviderException as exc:
            async with self._session.begin():
                attempt = await self._invoices.get_payment_attempt_or_raise(attempt.id)
                attempt.fail(message=str(exc))
            raise

        async with self._session.begin():
            invoice = await self._invoices.get_or_raise(invoice_id)
            attempt = await self._invoices.get_payment_attempt_or_raise(attempt.id)
            if provider_result.succeeded:
                attempt.succeed(provider_payment_id=provider_result.provider_payment_id)
                invoice.mark_paid()
                await self._outbox.add_event(InvoicePaid.from_model(invoice))
            else:
                attempt.fail(message=provider_result.error_message or "payment failed")

        return PaymentCollectionGet.from_models(invoice=invoice, attempt=attempt)
