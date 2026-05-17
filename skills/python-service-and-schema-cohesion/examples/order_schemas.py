from __future__ import annotations

from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.order import Order, OrderStatus


class OrderLineInput(BaseModel):
    product_id: UUID
    quantity: int
    unit_price: Decimal


class OrderLineGet(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: UUID
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class OrderGet(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_id: UUID
    status: OrderStatus
    currency: str
    total: Decimal
    lines: list[OrderLineGet]

    @classmethod
    def from_model(cls, order: Order) -> Self:
        return cls.model_validate(order)


class PlaceOrderCommand(BaseModel):
    customer_id: UUID
    currency: str
    lines: list[OrderLineInput]

    def to_new_order(self) -> Order:
        order = Order.new(customer_id=self.customer_id, currency=self.currency)
        for line in self.lines:
            order.add_line(
                product_id=line.product_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
            )
        return order


class CancelOrderCommand(BaseModel):
    order_id: UUID
    reason: str


class RefundOrderCommand(BaseModel):
    order_id: UUID
    charge_id: str
    amount: Decimal
    reason: str
