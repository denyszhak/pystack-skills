from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.invoice import (
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    InvoiceTotals,
    PaymentAttempt,
    PaymentAttemptStatus,
)


class InvoiceCreate(BaseModel):
    customer_id: UUID
    currency: Annotated[str, Field(min_length=3, max_length=3)] = "USD"

    def to_new_invoice(self) -> Invoice:
        return Invoice.new(customer_id=self.customer_id, currency=self.currency)


class AddInvoiceLineCommand(BaseModel):
    description: Annotated[str, Field(min_length=1, max_length=500)]
    quantity: Annotated[int, Field(gt=0)]
    unit_price: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    tax_rate: Annotated[Decimal, Field(ge=0, le=1, max_digits=5, decimal_places=4)]


class CollectPaymentCommand(BaseModel):
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    payment_method_token: Annotated[str, Field(min_length=1, max_length=500)]


class InvoiceLineGet(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str
    quantity: int
    unit_price: Decimal
    tax_rate: Decimal
    subtotal: Decimal
    tax: Decimal

    @classmethod
    def from_model(cls, line: InvoiceLine) -> Self:
        return cls.model_validate(line)


class InvoiceTotalGet(BaseModel):
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    currency: str

    @classmethod
    def from_model(cls, invoice: Invoice) -> Self:
        return cls.from_totals(invoice.totals)

    @classmethod
    def from_totals(cls, totals: InvoiceTotals) -> Self:
        return cls(
            subtotal=totals.subtotal,
            tax=totals.tax,
            total=totals.total,
            currency=totals.currency,
        )


class InvoiceGet(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    currency: str
    status: InvoiceStatus
    issued_at: datetime | None
    paid_at: datetime | None
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    lines: list[InvoiceLineGet]

    @classmethod
    def from_model(cls, invoice: Invoice) -> Self:
        return cls.model_validate(invoice)


class PaymentAttemptGet(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    idempotency_key: str
    status: PaymentAttemptStatus
    amount: Decimal
    currency: str
    provider_payment_id: str | None
    error_message: str | None
    completed_at: datetime | None

    @classmethod
    def from_model(cls, attempt: PaymentAttempt) -> Self:
        return cls.model_validate(attempt)


class PaymentCollectionGet(BaseModel):
    invoice: InvoiceGet
    payment_attempt: PaymentAttemptGet

    @classmethod
    def from_models(cls, *, invoice: Invoice, attempt: PaymentAttempt) -> Self:
        return cls(
            invoice=InvoiceGet.from_model(invoice),
            payment_attempt=PaymentAttemptGet.from_model(attempt),
        )
