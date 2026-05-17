---
name: python-message-bus-outbox
description: |
  Use when the service is event-driven: publishing or consuming events through
  a message broker (Kafka, RabbitMQ, Redis Streams, NATS, SQS), or using an
  in-process bus to decouple side effects from a use case. Triggers on edits to
  `app/events/`, `app/handlers/`, `app/outbox/`, `app/consumers/`; on imports
  of `aiokafka`, `aio-pika`, `redis.asyncio`, `aiobotocore`; on user mentions
  of "message bus", "domain events", "outbox pattern", "event-driven", "saga",
  "process manager", "Kafka consumer", "publisher". Encodes: in-process message
  bus, outbox table for at-least-once cross-process delivery, idempotent
  handlers, consumer layout for inbound subscribers, producer layout for
  outbound publishers.
  Do NOT use for: services with one consumer and no cross-process needs —
  direct function calls are simpler. The skill draws a clear line.
---

# Message bus and outbox

Event-driven architecture is a first-class option, not an exotic one. If your service publishes events to Kafka, consumes from RabbitMQ, or even just decouples in-process side effects via a local bus, this skill encodes the canonical shape.

The pattern earns its keep when:

- Multiple consumers need the same event (place order → email + analytics + webhook + warehouse)
- Side effects must survive crashes — the outbox ensures at-least-once delivery even if the publishing process dies after commit
- You're crossing process boundaries (publishing to Kafka / RabbitMQ / Redis Streams / NATS / SQS)
- You want loose coupling between use cases (saga / process manager)
- You're integrating with external services that already publish events you can subscribe to

The pattern is overkill when your service has exactly one consumer of an event AND no cross-process needs — `await self._emailer.send(...)` directly works fine for that case. The line is "do I need pub/sub semantics, or am I just sequencing function calls?"

This skill encodes the in-process bus + outbox + consumer/producer layout modernized for async Python.

## When to use this skill

- The service is event-driven (publishes, consumes, or both)
- You're adding Kafka / RabbitMQ / Redis Streams / NATS / SQS integration
- You need at-least-once delivery via the outbox pattern
- You're building a saga / process manager
- You want to decouple in-process side effects from the use case that triggered them

## Layout — where things go

Inbound and outbound are different concerns; the layout reflects that.

```
app/
  clients/                  # OUTBOUND: anything we call or publish TO
    openai.py
    stripe.py
    kafka.py                # KafkaProducer wrapper (publish methods only)
    rabbitmq.py             # publisher side
  consumers/                # INBOUND: anything we subscribe TO
    __init__.py             # provide_consumers() — registers consumers in lifespan
    order_consumer.py       # subscribes to "orders" topic, dispatches to services
    payment_consumer.py
  events/                   # in-process domain events (frozen dataclasses)
    order.py                # OrderPlaced, OrderCancelled
  schemas/
    events.py               # CROSS-PROCESS event wire shapes (Pydantic, for serialization)
  outbox/                   # outbox table model + dispatcher worker
    __init__.py
    model.py                # OutboxEntry (SA model)
    dispatcher.py           # background worker that drains the outbox
  handlers/                 # in-process handlers (for the local message bus)
    email_on_order_placed.py
    analytics_on_order_placed.py
  common/
    message_bus.py          # the in-process bus
```

**Producers (Kafka/RabbitMQ/etc. publish side) → `app/clients/`.** They're outbound calls that the *service* makes. Same pattern as HTTP clients: wrapped, configured, lifecycle-managed via `init_X_client` / `cleanup_X_client`.

**Consumers (Kafka/RabbitMQ/etc. subscribe side) → `app/consumers/`.** They're inbound entry points, conceptually parallel to `app/api/` for HTTP. Each consumer file owns one topic/queue, parses messages into schemas, dispatches to services. Lifecycle: started as a background task in `lifespan`.

**Events:**
- **In-process** (the local message bus pattern) → `app/events/`. Frozen dataclasses. Pure Python; not serialized over the wire.
- **Cross-process** (published to Kafka, consumed from RabbitMQ) → `app/schemas/events.py` (or `app/schemas/events/`). Pydantic models. They're I/O shapes — versioned, validated, JSON-serializable.

The two event types are different things; don't conflate them. Internal events flow through the message bus; external events flow through producers/consumers. A single use case can produce both — emit an internal event for `email_on_order_placed` *and* publish an external event for the warehouse service.

**Outbox** → `app/outbox/` as its own subpackage. The outbox table is technically a `models/` entry, but the dispatcher worker, the polling loop, and the entry's special semantics warrant a dedicated module.

## The rules

### 1. Events live in `app/events/` as frozen dataclasses

```python
# app/events/order.py
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPlaced:
    order_id: UUID
    customer_id: UUID
    placed_at: datetime
    total: Decimal
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCancelled:
    order_id: UUID
    cancelled_at: datetime
    reason: str
```

Past-tense names. Carry just enough data for handlers to act without re-fetching. Frozen because facts don't change.

### 2. Handlers live in `app/handlers/`, one file per concern

```python
# app/handlers/email_on_order_placed.py
from app.clients.email import EmailClient
from app.events.order import OrderPlaced
from app.repos.customer import CustomerRepo


async def email_on_order_placed(
    event: OrderPlaced,
    *,
    customers: CustomerRepo,
    emailer: EmailClient,
) -> None:
    customer = await customers.get_or_raise(event.customer_id)
    await emailer.send(
        to=customer.email,
        subject="Your order is confirmed",
        body=f"Total: {event.total} {event.currency}",
    )
```

```python
# app/handlers/analytics_on_order_placed.py
async def track_on_order_placed(
    event: OrderPlaced,
    *,
    analytics: AnalyticsClient,
) -> None:
    await analytics.track("order.placed", {
        "order_id": str(event.order_id),
        "customer_id": str(event.customer_id),
        "total": float(event.total),
    })
```

One handler per file. The file name describes the concern (`email_on_order_placed`, not `handler_1`).

### 3. Message bus in `app/common/message_bus.py`

```python
# app/common/message_bus.py
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import structlog


_log = structlog.get_logger(__name__)


type Handler[E] = Callable[[E], Awaitable[None]]


class MessageBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler[Any]]] = defaultdict(list)

    def subscribe[E](self, event_type: type[E], handler: Handler[E]) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: object) -> None:
        handlers = self._handlers.get(type(event), [])
        _log.info("bus.publish", event=type(event).__name__, handlers=len(handlers))
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                _log.exception("bus.handler.failed",
                               event=type(event).__name__,
                               handler=handler.__name__)
                # Swallow — handlers must not fail the publishing service.
                # For at-least-once, use the outbox pattern (rule 5+).
```

In-process. One handler per event type can be registered multiple times. Failures in handlers are logged and swallowed — the publisher's transaction has already committed.

### 4. Wire handlers at app startup

```python
# app/setup.py — inside provide_app or lifespan
from app.common.message_bus import MessageBus
from app.events.order import OrderCancelled, OrderPlaced
from app.handlers import (
    email_on_order_placed,
    track_on_order_placed,
    notify_warehouse_on_order_cancelled,
)


def _wire_message_bus(app: FastAPI) -> None:
    bus = MessageBus()
    # Handlers need their own deps. They're closures over the app or
    # take request-scoped deps via a partial — depends on the handler.
    bus.subscribe(OrderPlaced, lambda e: email_on_order_placed(e, ...))
    bus.subscribe(OrderPlaced, lambda e: track_on_order_placed(e, ...))
    bus.subscribe(OrderCancelled, lambda e: notify_warehouse_on_order_cancelled(e, ...))
    app.state.bus = bus
```

(Real wiring is finicky because handlers need request-scoped deps. The cleanest pattern: handlers are factory functions that take deps once at registration time and return the actual handler, which then takes only the event.)

### 5. Outbox for at-least-once delivery — the in-process bus alone isn't reliable

The in-process bus dispatches handlers *after* the service transaction succeeds. If the process crashes between transaction success and dispatch, you've persisted the state change but lost the events. For cross-process integration, that's unacceptable.

The outbox pattern fixes this:

1. The service writes the state change AND inserts the events into an `outbox` table in the same transaction.
2. A separate worker reads the outbox, dispatches events (or publishes to Kafka), and marks rows as processed.
3. Crash recovery: unprocessed rows get retried on next worker run.

```python
# app/models/outbox.py
from datetime import datetime, UTC
from uuid import UUID, uuid4

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class OutboxEntry(Base):
    __tablename__ = "outbox"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_type: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    processed_at: Mapped[datetime | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(default=None)
```

```python
# app/services/checkout.py
import json
from dataclasses import asdict

from app.events.order import OrderPlaced
from app.models.outbox import OutboxEntry


class CheckoutService:
    async def place_order(self, cmd: PlaceOrderCommand) -> OrderGet:
        async with self._session.begin():
            order = cmd.to_new_order()
            order.place()
            await self._orders.add(order)

            # Same transaction — outbox + state change are atomic
            event = OrderPlaced(
                order_id=order.id,
                customer_id=order.customer_id,
                placed_at=order.placed_at,
                total=order.total,
                currency=order.currency,
            )
            self._session.add(OutboxEntry(
                event_type="OrderPlaced",
                payload=asdict(event),
            ))

        return OrderGet.from_model(order)
```

### 6. Outbox worker — separate process, polls the outbox table

```python
# app/workers/outbox_dispatcher.py
import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.message_bus import MessageBus
from app.events.order import OrderPlaced, OrderCancelled
from app.models.outbox import OutboxEntry


_log = structlog.get_logger(__name__)

_EVENT_TYPES: dict[str, type] = {
    "OrderPlaced": OrderPlaced,
    "OrderCancelled": OrderCancelled,
}


async def dispatch_outbox(session_factory: async_sessionmaker, bus: MessageBus) -> None:
    async with session_factory() as session:
        stmt = select(OutboxEntry).where(OutboxEntry.processed_at.is_(None)).limit(100)
        result = await session.scalars(stmt)
        entries = list(result)

    for entry in entries:
        event_cls = _EVENT_TYPES.get(entry.event_type)
        if event_cls is None:
            _log.error("outbox.unknown_event_type", type=entry.event_type)
            continue
        event = event_cls(**entry.payload)
        try:
            await bus.publish(event)
            async with session_factory() as session:
                entry.processed_at = datetime.now(UTC)
                await session.merge(entry)
                await session.commit()
        except Exception as exc:
            _log.exception("outbox.dispatch.failed", entry_id=entry.id)
            async with session_factory() as session:
                entry.error = str(exc)
                await session.merge(entry)
                await session.commit()


async def run_outbox_loop(session_factory: async_sessionmaker, bus: MessageBus) -> None:
    while True:
        await dispatch_outbox(session_factory, bus)
        await asyncio.sleep(1.0)
```

Run as a separate process (`python -m app.workers.outbox_dispatcher`) or as an asyncio task spun up in `lifespan` for single-instance deployments.

### 7. Consumers subscribe in lifespan; one consumer per topic, dispatching to services

Consumers are inbound entry points — conceptually parallel to FastAPI routes for HTTP. Each consumer subscribes to one topic / queue, parses messages into schemas, dispatches to services, and acks (or rejects, for redelivery).

```python
# app/consumers/order_consumer.py
import structlog
from aiokafka import AIOKafkaConsumer

from app.schemas.events import OrderPlacedEvent
from app.services.fulfillment import FulfillmentService


log = structlog.get_logger(__name__)


class OrderConsumer:
    def __init__(self, *, kafka: AIOKafkaConsumer, fulfillment: FulfillmentService) -> None:
        self._kafka = kafka
        self._fulfillment = fulfillment

    async def run(self) -> None:
        async for message in self._kafka:
            try:
                event = OrderPlacedEvent.model_validate_json(message.value)
                await self._fulfillment.on_order_placed(event)
            except Exception:
                log.exception("consumer.failed", topic=message.topic, offset=message.offset)
                # The consumer group's offset-commit policy decides redelivery.
                raise
```

Lifecycle in `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config: AppConfig = app.state.config
    await init_db_pool(app, config.db)
    await init_openai_client(app, config.openai)
    await init_kafka_consumer(app, config.kafka)

    consumer_task = asyncio.create_task(app.state.order_consumer.run())

    try:
        yield
    finally:
        consumer_task.cancel()
        await app.state.order_consumer.close()
        await close_db_pool(app)
```

Key rules:
- **One file per topic / queue.** A file named for what it consumes (`order_consumer.py`, not `consumer_1.py`).
- **The consumer parses, the service decides.** The consumer does message → schema → `await self._service.method(event)`. No business logic in the consumer.
- **Schemas (in `app/schemas/events.py`) are the wire contract.** Use Pydantic for parsing untrusted inbound JSON. Validate early; if it fails to parse, the consumer's error policy (dead letter? skip? halt?) decides what to do.
- **Background task in `lifespan`.** Started with `asyncio.create_task(consumer.run())`. Cancelled cleanly at shutdown.
- **For multi-replica deployments**, use the broker's consumer group semantics (Kafka consumer groups, RabbitMQ queue sharding) — the broker handles work distribution. Don't try to coordinate in-app.

### 8. Handlers must be idempotent

The outbox guarantees *at least once* delivery. Handlers may receive the same event twice (worker crashes after dispatch, before marking processed). Make them safe to call twice with the same input.

Common patterns:
- Idempotency key derived from event (`event.order_id` as the natural key for "this order was processed")
- Check-then-act guarded by unique constraint or upsert

```python
async def email_on_order_placed(event: OrderPlaced, *, emailer, customers, repo):
    # Skip if we've already sent this email
    sent = await repo.was_sent(event.order_id)
    if sent:
        return
    await emailer.send(...)
    await repo.mark_sent(event.order_id)
```

### 9. Don't put business logic in handlers

Handlers translate an event into a side effect. Logic (decisions, validation, state changes) belongs in services or aggregate methods.

```python
# Bad — handler making business decisions
async def maybe_refund_on_order_cancelled(event: OrderCancelled, ...):
    order = await orders.get(event.order_id)
    if order.was_paid_via_card:
        await stripe.refund(...)


# Good — handler does one thing; decision was made by the canceller
async def refund_on_order_cancelled(event: OrderCancelled, ...):
    await stripe.refund(charge_id=event.charge_id, amount=event.amount)
```

If the cancelling service needs to decide "should we refund?", that decision happens in the service, and the event reflects the decision (`OrderRefundIssued`, not `OrderCancelled`).

### 10. Events flow forward; never query the past via events

Events are facts. Don't model "the customer's lifetime spending" as "consume all `OrderPlaced` events from the beginning of time." That's event sourcing, a different (much bigger) commitment. For aggregations, query the relational state directly.

### 11. Test handlers in isolation, then integration-test the bus

```python
# tests/unit/handlers/test_email_on_order_placed.py
async def test_handler_sends_email(emailer_mock, customer_repo_mock):
    event = OrderPlaced(order_id=uuid4(), customer_id=customer.id, ...)
    customer_repo_mock.get_or_raise.return_value = customer

    await email_on_order_placed(event, customers=customer_repo_mock, emailer=emailer_mock)

    emailer_mock.send.assert_called_once_with(to=customer.email, ...)


# tests/integration/test_outbox.py
async def test_outbox_dispatches_committed_events(session, bus):
    session.add(OutboxEntry(event_type="OrderPlaced", payload={...}))
    await session.commit()

    await dispatch_outbox(session_factory, bus)

    # Verify handler ran, entry marked processed
```

## When to break these rules

- **Direct function calls instead of events** — for in-process side effects with one consumer, just call the function. The bus is overhead.
- **In-process bus only, no outbox** — fine for fire-and-forget side effects where loss is acceptable (e.g. cache warming). For anything user-visible, use the outbox.
- **Synchronous handlers** — possible but the asyncio version is canonical; mixing sync and async handlers complicates the bus.

## Anti-patterns this displaces

- **God service** — `CheckoutService.place_order` that emails, tracks, webhooks, warehouses. Decoupling with events lets each concern live in its own handler.
- **Tight coupling via `await another_service.method(...)`** — fine when the call is a real dependency. Becomes a tangle when "place_order" calls 8 unrelated services. Events flip the dependency direction.
- **Cron jobs polling for "things to do"** — better modelled as an outbox: the source-of-truth transaction also records what work needs to happen.

## See also

- `python-pure-domain-layer` — aggregates with `pull_events()` to drain into the bus
- `python-aggregate-and-repo` — for SA-with-behavior; events are raised by services, not aggregates
- `python-service-and-schema-cohesion` — services that produce events
- `python-test-pyramid` — testing handlers and outbox workers
