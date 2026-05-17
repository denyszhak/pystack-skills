"""Pure domain Order aggregate — Cosmic Python style.

Framework-free. Sync. Behavior + invariants + events on the aggregate.
Imports stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import NewType, Self
from uuid import UUID, uuid4


OrderId = NewType("OrderId", UUID)
CustomerId = NewType("CustomerId", UUID)
ProductId = NewType("ProductId", UUID)


class OrderStatus(StrEnum):
    DRAFT = "draft"
    PLACED = "placed"
    PAID = "paid"
    CANCELLED = "cancelled"


class DomainException(Exception): ...
class NegativeAmountException(DomainException): ...
class InvalidCurrencyException(DomainException): ...
class CurrencyMismatchException(DomainException): ...
class OrderAlreadyPlacedException(DomainException): ...
class EmptyOrderException(DomainException): ...
class OrderNotFoundException(DomainException): ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise NegativeAmountException(f"amount must be >= 0, got {self.amount}")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise InvalidCurrencyException(f"currency must be 3 letters, got {self.currency!r}")

    def __add__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise CurrencyMismatchException(f"{self.currency} vs {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderLine:
    product_id: ProductId
    quantity: int
    unit_price: Money

    @property
    def subtotal(self) -> Money:
        return Money(
            amount=self.unit_price.amount * self.quantity,
            currency=self.unit_price.currency,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPlaced:
    order_id: OrderId
    customer_id: CustomerId
    placed_at: datetime
    total: Money


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCancelled:
    order_id: OrderId
    cancelled_at: datetime
    reason: str


type OrderEvent = OrderPlaced | OrderCancelled


@dataclass(slots=True, kw_only=True)
class Order:
    id: OrderId
    customer_id: CustomerId
    status: OrderStatus = OrderStatus.DRAFT
    lines: list[OrderLine] = field(default_factory=list)
    events: list[OrderEvent] = field(default_factory=list)

    @classmethod
    def open(cls, *, customer_id: CustomerId) -> Self:
        return cls(id=OrderId(uuid4()), customer_id=customer_id)

    @property
    def total(self) -> Money:
        if not self.lines:
            return Money(amount=Decimal("0"), currency="USD")
        running = self.lines[0].subtotal
        for line in self.lines[1:]:
            running = running + line.subtotal
        return running

    def add_line(self, line: OrderLine) -> None:
        if self.status is not OrderStatus.DRAFT:
            raise OrderAlreadyPlacedException(self.id)
        self.lines.append(line)

    def place(self) -> None:
        if self.status is not OrderStatus.DRAFT:
            raise OrderAlreadyPlacedException(self.id)
        if not self.lines:
            raise EmptyOrderException(self.id)
        self.status = OrderStatus.PLACED
        self.events.append(
            OrderPlaced(
                order_id=self.id,
                customer_id=self.customer_id,
                placed_at=datetime.now(UTC),
                total=self.total,
            )
        )

    def cancel(self, *, reason: str) -> None:
        if self.status is OrderStatus.CANCELLED:
            return
        self.status = OrderStatus.CANCELLED
        self.events.append(
            OrderCancelled(
                order_id=self.id,
                cancelled_at=datetime.now(UTC),
                reason=reason,
            )
        )

    def pull_events(self) -> list[OrderEvent]:
        drained, self.events = self.events, []
        return drained
