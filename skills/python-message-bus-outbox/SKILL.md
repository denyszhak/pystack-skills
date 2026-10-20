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
license: MIT
compatibility: Python 3.12+ services using FastAPI, SQLAlchemy 2.x (async), and PostgreSQL; a broker client (aiokafka, aio-pika, ...) when publishing or consuming.
metadata:
  tier: opt-in
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
    model.py                # OutboxEntry (SA model) + event serialization
    repo.py                 # OutboxRepo: add(event), claim_next()
    dispatcher.py           # background worker that drains the outbox
  handlers/                 # in-process handlers (for the local message bus)
    __init__.py             # build_message_bus(...) — the one place handlers are wired
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

### 2. Handlers live in `app/handlers/`, one factory per file

Each handler module exports a **factory**: it takes the handler's dependencies once, at startup, and returns the handler — an `async def handle(event)` that takes only the event.

```python
# app/handlers/email_on_order_placed.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.email import EmailClient
from app.common.message_bus import Handler
from app.events.order import OrderPlaced
from app.repos.customer import CustomerRepo


def email_on_order_placed(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    emailer: EmailClient,
) -> Handler[OrderPlaced]:
    async def handle(event: OrderPlaced) -> None:
        async with session_factory() as session:
            customer = await CustomerRepo(session).get_or_raise(event.customer_id)

        await emailer.send(
            to=customer.email,
            subject="Your order is confirmed",
            body=f"Total: {event.total} {event.currency}",
        )

    return handle
```

```python
# app/handlers/analytics_on_order_placed.py
from app.clients.analytics import AnalyticsClient
from app.common.message_bus import Handler
from app.events.order import OrderPlaced


def track_on_order_placed(*, analytics: AnalyticsClient) -> Handler[OrderPlaced]:
    async def handle(event: OrderPlaced) -> None:
        await analytics.track("order.placed", {
            "order_id": str(event.order_id),
            "customer_id": str(event.customer_id),
            "total": str(event.total),
        })

    return handle
```

Handlers are **app-lifetime**. They run after the request that produced the event has finished — often in another process, via the outbox — so they never receive the request's `AsyncSession`, repos, or services. The rules that follow:

- **Dependencies are app-lifetime resources only:** `session_factory` (`app.state.db_session_factory`), clients, config. Never a session, repo, or service instance.
- **One short-lived session per event.** A handler that needs the DB opens `async with session_factory() as session:` inside `handle`, builds the repos it needs from that session, and closes it.
- **Close the session before slow external I/O.** Load what you need, leave the `async with`, then call the email/HTTP client — don't hold a pooled connection across a network call.
- **A handler that writes owns its own transaction:** `async with session_factory() as session, session.begin():`.

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
        # not `event=` — structlog's first positional parameter is already named `event`
        _log.info("bus.publish", event_type=type(event).__name__, handlers=len(handlers))
        failures: list[Exception] = []
        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise ExceptionGroup(f"{len(failures)} handler(s) failed for {type(event).__name__}", failures)
```

In-process. An event type can have any number of handlers. Every handler runs even after an earlier one fails; the failures are then raised together as one `ExceptionGroup`.

**The bus never swallows a failure — its caller decides what a failure means.** The outbox dispatcher (rule 6) catches it and leaves the row for a retry; that is what makes delivery at-least-once. A bus that logs and swallows makes the dispatcher mark every row processed, including the ones whose handlers failed. The only caller that discards failures is a fire-and-forget publish after commit (see "When to break these rules"), and it does so explicitly at the call site.

### 4. Wire handlers in one `build_message_bus` function

```python
# app/handlers/__init__.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.analytics import AnalyticsClient
from app.clients.email import EmailClient
from app.clients.warehouse import WarehouseClient
from app.common.message_bus import MessageBus
from app.events.order import OrderCancelled, OrderPlaced
from app.handlers.analytics_on_order_placed import track_on_order_placed
from app.handlers.email_on_order_placed import email_on_order_placed
from app.handlers.warehouse_on_order_cancelled import notify_warehouse_on_order_cancelled


def build_message_bus(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    emailer: EmailClient,
    analytics: AnalyticsClient,
    warehouse: WarehouseClient,
) -> MessageBus:
    bus = MessageBus()
    bus.subscribe(OrderPlaced, email_on_order_placed(session_factory=session_factory, emailer=emailer))
    bus.subscribe(OrderPlaced, track_on_order_placed(analytics=analytics))
    bus.subscribe(OrderCancelled, notify_warehouse_on_order_cancelled(warehouse=warehouse))
    return bus
```

Build the bus in `lifespan`, after the DB pool and clients it needs are initialized:

```python
# app/setup.py — inside lifespan's AsyncExitStack, after init_db_pool / init_*_client
app.state.bus = build_message_bus(
    session_factory=app.state.db_session_factory,
    emailer=app.state.email_client,
    analytics=app.state.analytics_client,
    warehouse=app.state.warehouse_client,
)
```

`build_message_bus` is the single wiring point. The API process, the outbox worker process (rule 6), and tests all call it with their own resources — there is no second, hand-rolled wiring anywhere.

### 5. Outbox for at-least-once delivery — the in-process bus alone isn't reliable

The in-process bus dispatches handlers *after* the service transaction succeeds. If the process crashes between transaction success and dispatch, you've persisted the state change but lost the events. For cross-process integration, that's unacceptable.

The outbox pattern fixes this:

1. The service writes the state change AND inserts the events into an `outbox` table in the same transaction.
2. A separate worker reads the outbox, dispatches events (or publishes to Kafka), and marks rows as processed.
3. Crash recovery: unprocessed rows get retried on next worker run.

**Before implementing the outbox, read [references/outbox.md](references/outbox.md)** — the complete `app/outbox/model.py`, `repo.py`, and `dispatcher.py`. Copy them as a set. The shapes:

```python
# app/outbox/model.py — shape
class OutboxEntry(Base):
    # id, event_type, payload (JSONB), attempts, error,
    # created_at / available_at / processed_at — all DateTime(timezone=True)

    @classmethod
    def from_event(cls, event: OutboxEvent) -> Self: ...   # TypeAdapter(...).dump_python(event, mode="json")
    def to_event(self) -> OutboxEvent: ...                   # TypeAdapter(...).validate_python(self.payload)
    def mark_processed(self) -> None: ...
    def record_failure(self, exc: Exception) -> None: ...   # attempts += 1, available_at += 2**attempts s


# app/outbox/repo.py — shape
class OutboxRepo:
    async def add(self, event: OutboxEvent) -> None: ...    # session.add(OutboxEntry.from_event(event))
    async def claim_next(self) -> OutboxEntry | None: ...   # unprocessed, due, attempts < MAX_ATTEMPTS,
                                                             # FOR UPDATE SKIP LOCKED, LIMIT 1
```

**The payload is JSON, so the event is serialized, not `asdict`-ed.** `asdict(event)` leaves `UUID`, `Decimal`, and `datetime` values in the dict, and the JSON column can't store them. Pydantic's `TypeAdapter` handles stdlib dataclasses: `dump_python(mode="json")` turns those values into strings, and `validate_python` turns them back into the right types. That way `to_event()` returns an event equal to the one that was written. The serialization lives in the outbox module, so the event classes stay plain dataclasses with no Pydantic import.

**Timestamps are `DateTime(timezone=True)`.** `datetime.now(UTC)` is timezone-aware, and asyncpg rejects aware values for a plain `timestamp` column.

The service writes the event through the repo, inside its own transaction:

```python
# app/services/checkout.py
from app.events.order import OrderPlaced


class CheckoutService:
    async def place_order(self, cmd: PlaceOrderCommand) -> OrderGet:
        async with self._session.begin():
            order = cmd.to_new_order()
            order.place()
            await self._orders.add(order)

            # Same session, same transaction: the outbox row commits with the
            # state change, or neither does.
            await self._outbox.add(OrderPlaced(
                order_id=order.id,
                customer_id=order.customer_id,
                placed_at=order.placed_at,
                total=order.total,
                currency=order.currency,
            ))

        return OrderGet.from_model(order)
```

`self._outbox` is an `OutboxRepo` built from the request session, like every other repo the service uses (`get_outbox_repo` in `app/deps/repos.py`).

### 6. Outbox worker — separate process, polls the outbox table

```python
# app/outbox/dispatcher.py — core loop; full module (logging, run_outbox_loop) in references/outbox.md
async def dispatch_outbox(session_factory, bus: MessageBus, *, batch_size: int = 100) -> int:
    dispatched = 0
    for _ in range(batch_size):
        async with session_factory() as session, session.begin():       # one row, one transaction
            entry = await OutboxRepo(session).claim_next()
            if entry is None:
                break
            try:
                await bus.publish(entry.to_event())
            except Exception as exc:                                     # incl. the bus's ExceptionGroup
                entry.record_failure(exc)
            else:
                entry.mark_processed()
        dispatched += 1
    return dispatched
```

How it stays correct:

- **One row, one transaction, one lock.** `claim_next` uses `SELECT ... FOR UPDATE SKIP LOCKED`, so any number of workers or replicas can run the loop at once: a row locked by one worker is skipped by the others, and no row is delivered twice concurrently. The lock is held while that row's handlers run. The handlers open their own sessions, so each worker uses two pooled connections at a time; size the pool for that.
- **Success and failure both commit.** On success the row is marked processed. On failure, `record_failure` increments `attempts`, stores the error, and pushes `available_at` back exponentially (2 s, 4 s, 8 s, ... capped at an hour), so a failing row doesn't block or hot-loop the queue.
- **Dead rows stay for inspection.** After `MAX_ATTEMPTS` a row is no longer claimed. It stays in the table with its `error`, and that is your dead-letter queue. An unknown `event_type` fails through the same path instead of being skipped silently.
- **A crash re-delivers.** If the worker dies after the handlers ran but before the commit, the lock is released and the row is delivered again. That is at-least-once delivery; rule 8 makes it safe.

Run it as a separate process — a small entrypoint that creates the DB pool and clients, calls `build_message_bus(...)` (rule 4), and awaits `run_outbox_loop` — or as an asyncio task spun up in `lifespan` for single-instance deployments.

### 7. Consumers subscribe in lifespan; one consumer per topic, dispatching to services

Consumers are inbound entry points — conceptually parallel to FastAPI routes for HTTP. Each consumer subscribes to one topic / queue, parses messages into schemas, dispatches to services, and acks (or rejects, for redelivery).

**Before adding or changing a consumer, read [references/consumers.md](references/consumers.md)** — the full `OrderConsumer` class, its `init_order_consumer` / `cleanup_order_consumer` functions, and the `AsyncExitStack` lifespan that starts and cancels it.

Key rules:
- **One file per topic / queue.** A file named for what it consumes (`order_consumer.py`, not `consumer_1.py`).
- **The consumer parses, the service decides.** The consumer does message → schema → `await self._service.method(event)`. No business logic in the consumer.
- **Schemas (in `app/schemas/events.py`) are the wire contract.** Use Pydantic for parsing untrusted inbound JSON. Validate early; if it fails to parse, the consumer's error policy (dead letter? skip? halt?) decides what to do.
- **Background task in `lifespan`.** Started with `asyncio.create_task(consumer.run())` and registered on the same `AsyncExitStack`, so it is cancelled before the resources it uses are closed.
- **One session per message.** Same rule as handlers (rule 2): the consumer holds `session_factory`, never a session or a service built from one.
- **For multi-replica deployments**, use the broker's consumer group semantics (Kafka consumer groups, RabbitMQ queue sharding) — the broker handles work distribution. Don't try to coordinate in-app.

### 8. Handlers must be idempotent

The outbox guarantees *at least once* delivery. Handlers may receive the same event twice: the worker can crash after dispatch but before marking the row processed. A failed row is also retried as a whole, so when one handler fails, every handler on that event runs again, including the ones that already succeeded. Make them safe to call twice with the same input.

Common patterns:
- Idempotency key derived from event (`event.order_id` as the natural key for "this order was processed")
- Check-then-act guarded by unique constraint or upsert

```python
def email_on_order_placed(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    emailer: EmailClient,
) -> Handler[OrderPlaced]:
    async def handle(event: OrderPlaced) -> None:
        async with session_factory() as session:
            if await NotificationRepo(session).was_sent(order_id=event.order_id, kind="order_confirmation"):
                return                                   # already handled this event
            customer = await CustomerRepo(session).get_or_raise(event.customer_id)

        await emailer.send(to=customer.email, ...)

        async with session_factory() as session, session.begin():
            await NotificationRepo(session).mark_sent(order_id=event.order_id, kind="order_confirmation")

    return handle
```

A crash between `send` and `mark_sent` still sends twice — the sending side can't fully close that window. If the provider accepts an idempotency key, pass one derived from the event (`f"order-confirmation-{event.order_id}"`).

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

### 11. Test with real collaborators — no mocks

Same rules as `python-test-pyramid`: real Postgres, `httpx.MockTransport` doubles for HTTP clients, and plain recording functions where a handler is needed. No `Mock`, `AsyncMock`, `patch`, or `mocker`.

- **The bus** — unit tests with no DB. Subscribe a recording `async def record(event)` function, publish, and assert on what it recorded. Add a failing handler too: the other handlers must still run, and `publish` must raise an `ExceptionGroup`.
- **A handler** — through its factory. Pass `app.state.db_session_factory` and the real client built on its `MockTransport` double, seed the DB with real rows, call `handle(event)`, and assert on what the double recorded.
- **The dispatcher** — insert real rows with `OutboxEntry.from_event(...)` and run `dispatch_outbox`. On success, this test's row has `processed_at` set and the handler received an event equal to the original. On failure, the row is not processed, `attempts` is 1, and `available_at` has moved into the future.

**Before writing these tests, read [references/testing.md](references/testing.md)** for worked examples of all three.

## When to break these rules

- **Direct function calls instead of events** — for in-process side effects with one consumer, just call the function. The bus is overhead.
- **In-process bus only, no outbox** — fine for fire-and-forget side effects where loss is acceptable (e.g. cache warming). For anything user-visible, use the outbox. Publish after the transaction commits, and discard failures explicitly at the call site, because the use case has already succeeded:

  ```python
  try:
      await self._bus.publish(event)
  except* Exception:
      _log.exception("bus.publish.failed", event_type=type(event).__name__)
  ```
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
