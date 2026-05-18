from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar, Protocol, Self
from uuid import UUID

if TYPE_CHECKING:
    from app.models.invoice import Invoice


class InvoiceEvent(Protocol):
    event_type: ClassVar[str]

    def to_payload(self) -> dict[str, str]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceIssued:
    event_type: ClassVar[str] = "invoice.issued"

    invoice_id: UUID
    customer_id: UUID
    issued_at: datetime
    total: Decimal
    currency: str

    @classmethod
    def from_model(cls, invoice: Invoice) -> Self:
        if invoice.issued_at is None:
            raise ValueError("issued invoice event requires issued_at")
        return cls(
            invoice_id=invoice.id,
            customer_id=invoice.customer_id,
            issued_at=invoice.issued_at,
            total=invoice.total,
            currency=invoice.currency,
        )

    @classmethod
    def from_payload(cls, payload: dict[str, str]) -> Self:
        return cls(
            invoice_id=UUID(payload["invoice_id"]),
            customer_id=UUID(payload["customer_id"]),
            issued_at=datetime.fromisoformat(payload["issued_at"]),
            total=Decimal(payload["total"]),
            currency=payload["currency"],
        )

    def to_payload(self) -> dict[str, str]:
        return {
            "invoice_id": str(self.invoice_id),
            "customer_id": str(self.customer_id),
            "issued_at": self.issued_at.isoformat(),
            "total": str(self.total),
            "currency": self.currency,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoicePaid:
    event_type: ClassVar[str] = "invoice.paid"

    invoice_id: UUID
    customer_id: UUID
    paid_at: datetime
    total: Decimal
    currency: str

    @classmethod
    def from_model(cls, invoice: Invoice) -> Self:
        if invoice.paid_at is None:
            raise ValueError("paid invoice event requires paid_at")
        return cls(
            invoice_id=invoice.id,
            customer_id=invoice.customer_id,
            paid_at=invoice.paid_at,
            total=invoice.total,
            currency=invoice.currency,
        )

    @classmethod
    def from_payload(cls, payload: dict[str, str]) -> Self:
        return cls(
            invoice_id=UUID(payload["invoice_id"]),
            customer_id=UUID(payload["customer_id"]),
            paid_at=datetime.fromisoformat(payload["paid_at"]),
            total=Decimal(payload["total"]),
            currency=payload["currency"],
        )

    def to_payload(self) -> dict[str, str]:
        return {
            "invoice_id": str(self.invoice_id),
            "customer_id": str(self.customer_id),
            "paid_at": self.paid_at.isoformat(),
            "total": str(self.total),
            "currency": self.currency,
        }
