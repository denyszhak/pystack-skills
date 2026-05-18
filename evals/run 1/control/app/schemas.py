from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import InvoiceStatus, PaymentAttemptStatus

PositiveQuantity = Annotated[Decimal, Field(gt=Decimal("0"), max_digits=12, decimal_places=2)]
Money = Annotated[Decimal, Field(ge=Decimal("0"), max_digits=12, decimal_places=2)]
TaxRate = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4),
]


class CustomerCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    email: EmailStr


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    created_at: datetime


class InvoiceCreate(BaseModel):
    pass


class InvoiceLineCreate(BaseModel):
    description: Annotated[str, Field(min_length=1, max_length=500)]
    quantity: PositiveQuantity
    unit_price: Money
    tax_rate: TaxRate


class InvoiceLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal
    tax_amount: Decimal
    line_total: Decimal
    created_at: datetime


class InvoiceTotals(BaseModel):
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal


class InvoiceRead(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    status: InvoiceStatus
    created_at: datetime
    issued_at: datetime | None
    paid_at: datetime | None
    lines: list[InvoiceLineRead]
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal


class PaymentAttemptCreate(BaseModel):
    payment_method_token: Annotated[str, Field(min_length=1, max_length=255)]


class PaymentAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    idempotency_key: str
    status: PaymentAttemptStatus
    amount: Decimal
    provider_payment_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime

    invoice_status: InvoiceStatus
