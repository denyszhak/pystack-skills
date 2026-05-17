"""Typed ID example — NewType, Self, and Protocol working together."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NewType, Protocol, Self
from uuid import UUID, uuid4


OrderId = NewType("OrderId", UUID)
CustomerId = NewType("CustomerId", UUID)
ProductId = NewType("ProductId", UUID)


class CustomerStore(Protocol):
    async def get(self, customer_id: CustomerId) -> Customer | None: ...
    async def add(self, customer: Customer) -> None: ...


@dataclass(slots=True, kw_only=True)
class Customer:
    id: CustomerId
    name: str
    email: str

    @classmethod
    def new(cls, *, name: str, email: str) -> Self:
        return cls(id=CustomerId(uuid4()), name=name, email=email)


@dataclass(slots=True, kw_only=True)
class Order:
    id: OrderId
    customer_id: CustomerId
    product_ids: list[ProductId] = field(default_factory=list)

    @classmethod
    def new(cls, *, customer_id: CustomerId) -> Self:
        return cls(id=OrderId(uuid4()), customer_id=customer_id)

    def add_product(self, product_id: ProductId) -> None:
        self.product_ids.append(product_id)


async def example(store: CustomerStore) -> None:
    customer = Customer.new(name="Alice", email="alice@example.com")
    await store.add(customer)

    order = Order.new(customer_id=customer.id)
    order.add_product(ProductId(uuid4()))

    # Type system catches the swap:
    # await store.get(order.id)            # ty: OrderId is not CustomerId
    await store.get(customer.id)            # ok
