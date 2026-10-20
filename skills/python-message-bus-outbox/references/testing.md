# Testing the bus, handlers, and outbox — worked examples

Reference for rule 11 of `python-message-bus-outbox`. Same rules as `python-test-pyramid`: real Postgres, `httpx.MockTransport` doubles for HTTP clients, plain recording functions where a handler is needed. No `Mock`, `AsyncMock`, `patch`, or `mocker`.

The examples share one helper:

```python
def _order_placed() -> OrderPlaced:
    return OrderPlaced(
        order_id=uuid4(),
        customer_id=uuid4(),
        placed_at=datetime.now(UTC),
        total=Decimal("20.00"),
        currency="USD",
    )
```

## The bus — unit tests, recording handlers

```python
# tests/unit/common/test_message_bus.py
async def test_publish_delivers_event_to_every_subscriber() -> None:
    received: list[OrderPlaced] = []

    async def record(event: OrderPlaced) -> None:
        received.append(event)

    bus = MessageBus()
    bus.subscribe(OrderPlaced, record)
    bus.subscribe(OrderPlaced, record)
    event = _order_placed()

    await bus.publish(event)

    assert received == [event, event]


async def test_publish_runs_every_handler_then_raises_the_failures() -> None:
    received: list[OrderPlaced] = []

    async def fail(event: OrderPlaced) -> None:
        raise RuntimeError("smtp down")

    async def record(event: OrderPlaced) -> None:
        received.append(event)

    bus = MessageBus()
    bus.subscribe(OrderPlaced, fail)
    bus.subscribe(OrderPlaced, record)

    with pytest.raises(ExceptionGroup) as excinfo:
        await bus.publish(_order_placed())

    assert len(received) == 1                                  # the later handler still ran
    assert excinfo.group_contains(RuntimeError, match="smtp down")
```

## A handler — through its factory, real DB, real client on a transport double

```python
# tests/integration/handlers/test_email_on_order_placed.py
async def test_emails_the_customer(
    app: FastAPI,
    session: AsyncSession,
    email_mock: EmailMock,          # tests/doubles/email.py — MockTransport handler, records requests
    email_client: EmailClient,      # real EmailClient wired to email_mock (see python-test-pyramid)
) -> None:
    customer = Customer.new(name="Ada", email="ada@example.com")
    async with session.begin():
        await CustomerRepo(session).add(customer)
    handle = email_on_order_placed(session_factory=app.state.db_session_factory, emailer=email_client)

    await handle(OrderPlaced(
        order_id=uuid4(),
        customer_id=customer.id,
        placed_at=datetime.now(UTC),
        total=Decimal("20.00"),
        currency="USD",
    ))

    assert [sent["to"] for sent in email_mock.sent] == ["ada@example.com"]
```

## The dispatcher — real outbox rows

```python
# tests/integration/outbox/test_dispatcher.py
async def test_dispatch_delivers_the_event_and_marks_the_row_processed(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    received: list[OrderPlaced] = []

    async def record(event: OrderPlaced) -> None:
        received.append(event)

    bus = MessageBus()
    bus.subscribe(OrderPlaced, record)
    event = _order_placed()
    entry = OutboxEntry.from_event(event)
    async with session.begin():
        session.add(entry)

    await dispatch_outbox(app.state.db_session_factory, bus)

    await session.refresh(entry)
    assert entry.processed_at is not None
    assert event in received                                   # survived the JSON round trip intact


async def test_failed_dispatch_keeps_the_row_and_backs_off(app: FastAPI, session: AsyncSession) -> None:
    async def fail(event: OrderPlaced) -> None:
        raise RuntimeError("smtp down")

    bus = MessageBus()
    bus.subscribe(OrderPlaced, fail)
    entry = OutboxEntry.from_event(_order_placed())
    async with session.begin():
        session.add(entry)

    await dispatch_outbox(app.state.db_session_factory, bus)

    await session.refresh(entry)
    assert entry.processed_at is None
    assert entry.attempts == 1
    assert entry.available_at > datetime.now(UTC)
    assert "smtp down" in (entry.error or "")
```

Assert on *this* test's row (`entry`), not on "exactly one event was delivered". The test database is shared across tests, so the dispatcher may also pick up rows other tests left behind.
