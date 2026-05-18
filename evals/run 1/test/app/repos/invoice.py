from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.exceptions import UniqueViolationException
from app.models.invoice import (
    Invoice,
    InvoiceNotFoundException,
    PaymentAttempt,
    PaymentAttemptNotFoundException,
)


class InvoiceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, invoice_id: UUID) -> Invoice | None:
        return await self._session.get(
            Invoice,
            invoice_id,
            options=(selectinload(Invoice.lines), selectinload(Invoice.payment_attempts)),
        )

    async def get_or_raise(self, invoice_id: UUID) -> Invoice:
        invoice = await self.get(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundException(invoice_id)
        return invoice

    async def add(self, invoice: Invoice) -> None:
        self._session.add(invoice)
        await self._session.flush()

    async def add_payment_attempt(self, attempt: PaymentAttempt) -> None:
        self._session.add(attempt)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise UniqueViolationException("payment idempotency key already exists") from exc

    async def get_payment_attempt_by_idempotency_key(
        self,
        *,
        invoice_id: UUID,
        idempotency_key: str,
    ) -> PaymentAttempt | None:
        stmt = select(PaymentAttempt).where(
            PaymentAttempt.invoice_id == invoice_id,
            PaymentAttempt.idempotency_key == idempotency_key,
        )
        return await self._session.scalar(stmt)

    async def get_payment_attempt_or_raise(self, payment_attempt_id: UUID) -> PaymentAttempt:
        attempt = await self._session.get(PaymentAttempt, payment_attempt_id)
        if attempt is None:
            raise PaymentAttemptNotFoundException(payment_attempt_id)
        return attempt
