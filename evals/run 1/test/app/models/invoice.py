from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.common.exceptions import ConflictException, InvalidInputException, NotFoundException
from app.models.base import Base


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"


class PaymentAttemptStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InvoiceNotFoundException(NotFoundException):
    code = "invoice_not_found"

    def __init__(self, invoice_id: UUID) -> None:
        super().__init__(f"invoice {invoice_id} was not found")


class PaymentAttemptNotFoundException(NotFoundException):
    code = "payment_attempt_not_found"

    def __init__(self, payment_attempt_id: UUID) -> None:
        super().__init__(f"payment attempt {payment_attempt_id} was not found")


class InvoiceNotDraftException(ConflictException):
    code = "invoice_not_draft"

    def __init__(self, invoice_id: UUID) -> None:
        super().__init__(f"invoice {invoice_id} is not draft and cannot be modified")


class EmptyInvoiceException(InvalidInputException):
    code = "empty_invoice"

    def __init__(self, invoice_id: UUID) -> None:
        super().__init__(f"invoice {invoice_id} cannot be issued without line items")


class InvoiceAlreadyPaidException(ConflictException):
    code = "invoice_already_paid"

    def __init__(self, invoice_id: UUID) -> None:
        super().__init__(f"invoice {invoice_id} is already paid")


class InvoicePaymentNotAllowedException(ConflictException):
    code = "invoice_payment_not_allowed"

    def __init__(self, invoice_id: UUID) -> None:
        super().__init__(f"invoice {invoice_id} must be issued before payment can be collected")


class InvalidInvoiceLineException(InvalidInputException):
    code = "invalid_invoice_line"


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceTotals:
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    currency: str


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("customers.id"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        SAEnum(
            InvoiceStatus,
            values_callable=_enum_values,
            native_enum=False,
            validate_strings=True,
        ),
        default=InvoiceStatus.DRAFT,
        nullable=False,
    )
    issued_at: Mapped[datetime | None] = mapped_column(default=None)
    paid_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    payment_attempts: Mapped[list[PaymentAttempt]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @classmethod
    def new(cls, *, customer_id: UUID, currency: str) -> Self:
        return cls(
            id=uuid4(),
            customer_id=customer_id,
            currency=currency.upper(),
            status=InvoiceStatus.DRAFT,
        )

    @property
    def subtotal(self) -> Decimal:
        return _money(sum((line.subtotal for line in self.lines), Decimal("0.00")))

    @property
    def tax(self) -> Decimal:
        return _money(sum((line.tax for line in self.lines), Decimal("0.00")))

    @property
    def total(self) -> Decimal:
        return _money(self.subtotal + self.tax)

    @property
    def totals(self) -> InvoiceTotals:
        return InvoiceTotals(
            subtotal=self.subtotal,
            tax=self.tax,
            total=self.total,
            currency=self.currency,
        )

    def add_line(
        self,
        *,
        description: str,
        quantity: int,
        unit_price: Decimal,
        tax_rate: Decimal,
    ) -> None:
        if self.status is not InvoiceStatus.DRAFT:
            raise InvoiceNotDraftException(self.id)
        self.lines.append(
            InvoiceLine.new(
                invoice_id=self.id,
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                tax_rate=tax_rate,
            )
        )

    def issue(self) -> None:
        if self.status is not InvoiceStatus.DRAFT:
            raise InvoiceNotDraftException(self.id)
        if not self.lines:
            raise EmptyInvoiceException(self.id)
        self.status = InvoiceStatus.ISSUED
        self.issued_at = datetime.now(UTC)

    def ensure_payment_can_be_collected(self) -> None:
        if self.status is InvoiceStatus.PAID:
            raise InvoiceAlreadyPaidException(self.id)
        if self.status is not InvoiceStatus.ISSUED:
            raise InvoicePaymentNotAllowedException(self.id)

    def start_payment_attempt(self, *, idempotency_key: str) -> PaymentAttempt:
        self.ensure_payment_can_be_collected()
        attempt = PaymentAttempt.pending(
            invoice_id=self.id,
            idempotency_key=idempotency_key,
            amount=self.total,
            currency=self.currency,
        )
        self.payment_attempts.append(attempt)
        return attempt

    def mark_paid(self) -> None:
        if self.status is InvoiceStatus.PAID:
            raise InvoiceAlreadyPaidException(self.id)
        self.status = InvoiceStatus.PAID
        self.paid_at = datetime.now(UTC)


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("invoices.id"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    invoice: Mapped[Invoice] = relationship(back_populates="lines")

    @classmethod
    def new(
        cls,
        *,
        invoice_id: UUID,
        description: str,
        quantity: int,
        unit_price: Decimal,
        tax_rate: Decimal,
    ) -> Self:
        if quantity <= 0:
            raise InvalidInvoiceLineException("quantity must be positive")
        if unit_price < 0:
            raise InvalidInvoiceLineException("unit price cannot be negative")
        if tax_rate < 0 or tax_rate > 1:
            raise InvalidInvoiceLineException("tax rate must be between 0 and 1")
        return cls(
            id=uuid4(),
            invoice_id=invoice_id,
            description=description,
            quantity=quantity,
            unit_price=unit_price,
            tax_rate=tax_rate,
        )

    @property
    def subtotal(self) -> Decimal:
        return _money(self.unit_price * self.quantity)

    @property
    def tax(self) -> Decimal:
        return _money(self.subtotal * self.tax_rate)


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        UniqueConstraint(
            "invoice_id",
            "idempotency_key",
            name="uq_payment_attempt_invoice_idempotency_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("invoices.id"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[PaymentAttemptStatus] = mapped_column(
        SAEnum(
            PaymentAttemptStatus,
            values_callable=_enum_values,
            native_enum=False,
            validate_strings=True,
        ),
        default=PaymentAttemptStatus.PENDING,
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(200), default=None)
    error_message: Mapped[str | None] = mapped_column(String(1000), default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    invoice: Mapped[Invoice] = relationship(back_populates="payment_attempts")

    @classmethod
    def pending(
        cls,
        *,
        invoice_id: UUID,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
    ) -> Self:
        return cls(
            id=uuid4(),
            invoice_id=invoice_id,
            idempotency_key=idempotency_key,
            amount=amount,
            currency=currency,
            status=PaymentAttemptStatus.PENDING,
        )

    def succeed(self, *, provider_payment_id: str | None) -> None:
        self.status = PaymentAttemptStatus.SUCCEEDED
        self.provider_payment_id = provider_payment_id
        self.error_message = None
        self.completed_at = datetime.now(UTC)

    def fail(self, *, message: str) -> None:
        self.status = PaymentAttemptStatus.FAILED
        self.error_message = message
        self.completed_at = datetime.now(UTC)
