from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from app.common.exceptions import (
    InvalidInputException,
    ConflictException,
    NotFoundException,
)
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase): ...


class OrderStatus(StrEnum):
    DRAFT = "draft"
    PLACED = "placed"
    PAID = "paid"
    CANCELLED = "cancelled"


class OrderNotFoundException(NotFoundException):
    def __init__(self, order_id: UUID) -> None:
        super().__init__(f"order {order_id} not found")


class OrderAlreadyPlacedException(ConflictException):
    def __init__(self, order_id: UUID) -> None:
        super().__init__(f"order {order_id} is already placed")


class EmptyOrderException(InvalidInputException):
    def __init__(self, order_id: UUID) -> None:
        super().__init__(f"order {order_id} has no lines")


class Order(Base):
    __tablename__ = "order"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    status: Mapped[OrderStatus] = mapped_column(default=OrderStatus.DRAFT)
    placed_at: Mapped[datetime | None] = mapped_column(default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(default=None)
    cancelled_reason: Mapped[str | None] = mapped_column(default=None)
    currency: Mapped[str]
    lines: Mapped[list["OrderLine"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def total(self) -> Decimal:
        return sum((line.subtotal for line in self.lines), Decimal("0"))

    @classmethod
    def new(cls, *, customer_id: UUID, currency: str) -> Self:
        return cls(customer_id=customer_id, currency=currency)

    def add_line(self, *, product_id: UUID, quantity: int, unit_price: Decimal) -> None:
        if self.status is not OrderStatus.DRAFT:
            raise OrderAlreadyPlacedException(self.id)

        self.lines.append(
            OrderLine(
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
            )
        )

    def place(self) -> None:
        if self.status is not OrderStatus.DRAFT:
            raise OrderAlreadyPlacedException(self.id)

        if not self.lines:
            raise EmptyOrderException(self.id)

        self.status = OrderStatus.PLACED
        self.placed_at = datetime.now(UTC)

    def cancel(self, *, reason: str) -> None:
        if self.status is OrderStatus.CANCELLED:
            return

        self.status = OrderStatus.CANCELLED
        self.cancelled_at = datetime.now(UTC)
        self.cancelled_reason = reason


class OrderLine(Base):
    __tablename__ = "order_line"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("order.id"))
    product_id: Mapped[UUID]
    quantity: Mapped[int]
    unit_price: Mapped[Decimal]

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity
