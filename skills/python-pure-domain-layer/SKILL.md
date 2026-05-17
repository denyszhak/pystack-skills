---
name: python-pure-domain-layer
description: |
  Use ONLY when the project has an explicit `app/domain/` directory, or the user
  explicitly asks for "DDD aggregate", "pure domain model", "framework-free
  invariants", "Cosmic Python style", "separate domain and ORM". Triggers on
  edits to `app/domain/`; on user mentions of Cosmic Python, ports and adapters,
  imperative SA mapping, `from_domain` / `to_domain`. Encodes: separate domain
  classes (frozen dataclass VOs, mutable aggregate roots), SA models that
  translate to/from domain via `from_domain` / `to_domain` methods, pulling
  domain events on the aggregate, sync-only domain code.
  Do NOT use for: default FastAPI + SA services — use `python-aggregate-and-repo`
  instead. The pure-domain pattern is an opt-in for invariant-dense systems
  (finance, fulfillment, complex state machines).
---

# Pure domain layer (Cosmic Python style)

This is the **opt-in alternative** to `python-aggregate-and-repo`. The default style (SA model with behavior) is faster to write and read; this style adds boilerplate in exchange for a domain that knows nothing about SQLAlchemy. Switch to this when:

- Your invariants are dense enough that you want sub-millisecond unit tests *without* a DB
- You expect the persistence story to change (Postgres → DynamoDB; or microservice → event-sourced)
- You have multiple persistence shapes for the same aggregate (write store + read store)
- You want the domain to be portable across services without dragging SA along

The cost: every aggregate exists in two places (the pure `app/domain/<x>.py` and the SA `app/models/<x>.py`), with translation methods (`from_domain` / `to_domain`) bridging them. That's real boilerplate. It pays back when invariants justify it.

This skill encodes the Cosmic Python pattern, modernized for Python 3.12+ typing.

## Relationship to the default skill

`python-aggregate-and-repo` (the default) and this skill are two points on the same tradeoff curve, both legitimate. The default trades strict framework-freedom for less code. This skill trades more boilerplate for a domain that knows nothing about SQLAlchemy.

**Context worth knowing:** When Cosmic Python was written (2020), the alternative to imperative mapping was untyped classic-style declarative — genuinely worse than pure domain. SA 2.0's typed `Mapped[]` style narrowed that gap considerably; `class Order(Base): id: Mapped[UUID] = mapped_column(primary_key=True)` is type-safe and unobtrusive. Whether that narrowing changes the calculus for your project depends on how dense your invariants are. Pick this skill when you want a domain that's truly framework-free; pick the default when the translation boilerplate would outweigh the gain.

Both choices are correct for their contexts.

## When to use this skill

- The codebase already has `app/domain/` (this is the strong signal)
- You're starting a system with rich business invariants (insurance pricing, financial settlement, multi-step fulfillment)
- You want pure-Python aggregate tests that run in microseconds

## The rules

### 1. `domain/` is framework-free

```python
# app/domain/order.py
from dataclasses import dataclass, field
from datetime import datetime, UTC
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


@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise NegativeAmountException(self.amount)
        if len(self.currency) != 3:
            raise InvalidCurrencyException(self.currency)

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise CurrencyMismatchException(self.currency, other.currency)
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


# ── Events: past-tense facts, frozen ──────────────────────────────────────
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


# ── Domain errors ─────────────────────────────────────────────────────────
class DomainException(Exception): ...
class NegativeAmountException(DomainException): ...
class InvalidCurrencyException(DomainException): ...
class CurrencyMismatchException(DomainException): ...
class OrderAlreadyPlacedException(DomainException): ...
class EmptyOrderException(DomainException): ...
class OrderNotFoundException(DomainException): ...


# ── Aggregate root: mutable, owns invariants ──────────────────────────────
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
        self.events.append(OrderPlaced(
            order_id=self.id,
            customer_id=self.customer_id,
            placed_at=datetime.now(UTC),
            total=self.total,
        ))

    def cancel(self, *, reason: str) -> None:
        if self.status is OrderStatus.CANCELLED:
            return
        self.status = OrderStatus.CANCELLED
        self.events.append(OrderCancelled(
            order_id=self.id,
            cancelled_at=datetime.now(UTC),
            reason=reason,
        ))

    def pull_events(self) -> list[OrderEvent]:
        drained, self.events = self.events, []
        return drained
```

Imports in `app/domain/order.py`: stdlib only. No `sqlalchemy`, no `fastapi`, no `pydantic`. Tests of this file need no DB and no async setup.

### 2. Value objects are frozen + slots + kw_only; aggregates are mutable + slots + kw_only

`Money`, `OrderLine`, events: `@dataclass(frozen=True, slots=True, kw_only=True)`. Equality by value, hashable, no identity.

`Order`: `@dataclass(slots=True, kw_only=True)` — mutable because `place()` and `cancel()` change state, but identity-based (the `id` field is what makes two `Order`s the same).

### 3. Aggregate methods are sync; no `async` in `domain/`

Domain methods don't do I/O. They mutate state, raise exceptions, append events. The service does the I/O before and after.

```python
def place(self) -> None: ...      # sync — no DB, no HTTP
def cancel(self, *, reason: str) -> None: ...
```

If a domain method needs external data to make a decision, the service fetches it and passes it in:

```python
# service
inventory_at_warehouse = await self._inventory.get(product_id)
order.add_line(line=OrderLine(...), available_inventory=inventory_at_warehouse)
```

### 4. Events on the aggregate; service drains them after the transaction

The aggregate accumulates events during method calls. The service collects them with `pull_events()` after the transaction succeeds, and dispatches them via the message bus.

```python
# service
async def place_order(self, cmd: PlaceOrderCommand) -> OrderGet:
    async with self._session.begin():
        order = Order.open(customer_id=cmd.customer_id)
        for line_input in cmd.lines:
            order.add_line(OrderLine(
                product_id=line_input.product_id,
                quantity=line_input.quantity,
                unit_price=Money(amount=line_input.unit_price, currency=cmd.currency),
            ))
        order.place()
        await self._orders.add(order)

    for event in order.pull_events():
        await self._bus.publish(event)
    return OrderGet.from_domain(order)
```

Events are *facts that already happened*. They're past-tense names (`OrderPlaced`, not `PlaceOrder`). They carry just enough data for handlers to act.

### 5. SA model is a separate translation surface

```python
# app/models/order.py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.order import (
    CustomerId,
    Money,
    Order,
    OrderId,
    OrderLine,
    OrderStatus,
    ProductId,
)


class Base(DeclarativeBase): ...


class OrderModel(Base):
    __tablename__ = "order"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    customer_id: Mapped[UUID]
    status: Mapped[str]
    currency: Mapped[str]
    lines: Mapped[list["OrderLineModel"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @classmethod
    def from_domain(cls, order: Order) -> "OrderModel":
        return cls(
            id=order.id,
            customer_id=order.customer_id,
            status=order.status.value,
            currency=order.lines[0].unit_price.currency if order.lines else "USD",
            lines=[OrderLineModel.from_domain(l) for l in order.lines],
        )

    def to_domain(self) -> Order:
        return Order(
            id=OrderId(self.id),
            customer_id=CustomerId(self.customer_id),
            status=OrderStatus(self.status),
            lines=[l.to_domain() for l in self.lines],
            events=[],
        )


class OrderLineModel(Base):
    __tablename__ = "order_line"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("order.id"))
    product_id: Mapped[UUID]
    quantity: Mapped[int]
    unit_price: Mapped[Decimal]
    currency: Mapped[str]

    @classmethod
    def from_domain(cls, line: OrderLine) -> "OrderLineModel":
        return cls(
            product_id=line.product_id,
            quantity=line.quantity,
            unit_price=line.unit_price.amount,
            currency=line.unit_price.currency,
        )

    def to_domain(self) -> OrderLine:
        return OrderLine(
            product_id=ProductId(self.product_id),
            quantity=self.quantity,
            unit_price=Money(amount=self.unit_price, currency=self.currency),
        )
```

The translation methods live on the SA model (cohesion: the model knows how to bridge to/from its domain counterpart). Domain stays clean.

### 6. Repos translate at the boundary

```python
# app/repos/order.py
class OrderRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, order_id: OrderId) -> Order | None:
        model = await self._session.get(OrderModel, order_id)
        return model.to_domain() if model else None

    async def get_or_raise(self, order_id: OrderId) -> Order:
        order = await self.get(order_id)
        if order is None:
            raise OrderNotFoundException(order_id)
        return order

    async def add(self, order: Order) -> None:
        self._session.add(OrderModel.from_domain(order))
        await self._session.flush()

    async def save(self, order: Order) -> None:
        await self._session.merge(OrderModel.from_domain(order))
```

Repo returns domain objects, not models. Services work with `Order` (the domain class), never `OrderModel`.

### 7. Schemas translate from domain, not from model

```python
# app/schemas/order.py
class OrderGet(BaseModel):
    id: UUID
    customer_id: UUID
    status: OrderStatus
    total: Decimal
    currency: str
    lines: list[OrderLineGet]

    @classmethod
    def from_domain(cls, order: Order) -> Self:
        return cls(
            id=order.id,
            customer_id=order.customer_id,
            status=order.status,
            total=order.total.amount,
            currency=order.total.currency,
            lines=[OrderLineGet.from_domain(l) for l in order.lines],
        )
```

The schema knows how to render a `Order` (domain class). It doesn't know about `OrderModel`.

### 8. Test the domain at sub-millisecond speed

```python
# tests/unit/domain/test_order.py
from app.domain.order import (
    CustomerId, Money, Order, OrderLine, OrderPlaced, ProductId,
    EmptyOrderException,
)


def test_placing_empty_order_raises() -> None:
    order = Order.open(customer_id=CustomerId(uuid4()))
    with pytest.raises(EmptyOrderException):
        order.place()


def test_place_emits_order_placed_event() -> None:
    order = Order.open(customer_id=CustomerId(uuid4()))
    order.add_line(OrderLine(
        product_id=ProductId(uuid4()),
        quantity=1,
        unit_price=Money(amount=Decimal("10"), currency="USD"),
    ))
    order.place()

    events = order.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], OrderPlaced)
    assert events[0].total == Money(amount=Decimal("10"), currency="USD")
```

No DB. No `pytest-asyncio`. No fixtures. Sub-millisecond. This is the *whole point* of the pure-domain pattern — these tests are dirt cheap, so you write hundreds.

### 9. SA Mapper note: NO imperative mapping

Cosmic Python's book uses `mapper_registry.map_imperatively(Order, orders_table)` to make the *domain* class also be the SA-mapped class. This skill rejects that approach: it forces the domain class to satisfy SA's identity-map needs and breaks down with nested value objects (Money), composites, and lazy loading.

Instead, keep two classes (`Order` and `OrderModel`) with explicit translation. More code, but explicit, type-safe, and clean.

### 10. When in doubt, switch back to `python-aggregate-and-repo`

If the boilerplate of translation is more code than the invariants you're protecting, the pure-domain pattern isn't earning its keep. Switch to behavior-on-SA-model and delete `app/domain/`.

It's also fine to mix: most aggregates use the SA-with-behavior pattern, one or two with rich invariants get the pure-domain treatment. Per-aggregate is a valid hybrid.

## When to break these rules

- **Imperative mapping** — if you're willing to live with the trade-offs, it does eliminate the translation code. Skim Cosmic Python's chapter 2 carefully.
- **Async in domain** — forbidden by default. If you genuinely need a domain method to consult an external service (rare), pass the result in rather than awaiting in the domain.
- **Mutable events** — events are facts; facts don't change. Always frozen.

## See also

- `python-aggregate-and-repo` — the default style; consider this first
- `python-value-objects` — VOs in `domain/`
- `python-typing-idioms` — `NewType`, `Self`, narrowing
- `python-message-bus-outbox` — what to do with the events drained from `pull_events()`
- `python-service-and-schema-cohesion` — services that orchestrate domain aggregates
