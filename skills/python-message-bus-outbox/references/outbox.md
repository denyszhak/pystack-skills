# Outbox — full model, repo, and dispatcher

Reference for rules 5 and 6 of `python-message-bus-outbox`. Copy these three modules as a set; the dispatcher's correctness depends on the claim query and the failure bookkeeping on the model.

## `app/outbox/model.py`

```python
# app/outbox/model.py
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any, Final, Self
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import DateTime, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.events.order import OrderCancelled, OrderPlaced
from app.models.base import Base


type OutboxEvent = OrderPlaced | OrderCancelled

_EVENT_TYPES: Final[dict[str, type[OutboxEvent]]] = {
    event_cls.__name__: event_cls for event_cls in (OrderPlaced, OrderCancelled)
}
MAX_ATTEMPTS: Final = 10


class UnknownOutboxEventException(LookupError):
    def __init__(self, event_type: str) -> None:
        super().__init__(f"no event class registered for outbox event_type {event_type!r}")


@cache
def _adapter(event_cls: type[OutboxEvent]) -> TypeAdapter[OutboxEvent]:
    return TypeAdapter(event_cls)


class OutboxEntry(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_pending", "available_at", postgresql_where=text("processed_at IS NULL")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_type: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    attempts: Mapped[int] = mapped_column(default=0)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    error: Mapped[str | None] = mapped_column(default=None)

    @classmethod
    def from_event(cls, event: OutboxEvent) -> Self:
        return cls(
            event_type=type(event).__name__,
            payload=_adapter(type(event)).dump_python(event, mode="json"),
        )

    def to_event(self) -> OutboxEvent:
        event_cls = _EVENT_TYPES.get(self.event_type)
        if event_cls is None:
            raise UnknownOutboxEventException(self.event_type)
        return _adapter(event_cls).validate_python(self.payload)

    def mark_processed(self) -> None:
        self.processed_at = datetime.now(UTC)
        self.error = None

    def record_failure(self, exc: Exception) -> None:
        self.attempts += 1
        self.error = repr(exc)
        self.available_at = datetime.now(UTC) + timedelta(seconds=min(2**self.attempts, 3600))
```

Register every event type the outbox carries in `OutboxEvent` and `_EVENT_TYPES`. A row whose `event_type` isn't registered fails in `to_event()` and goes through the normal retry/dead-letter path.

## `app/outbox/repo.py`

```python
# app/outbox/repo.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.model import MAX_ATTEMPTS, OutboxEntry, OutboxEvent


class OutboxRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: OutboxEvent) -> None:
        self._session.add(OutboxEntry.from_event(event))

    async def claim_next(self) -> OutboxEntry | None:
        stmt = (
            select(OutboxEntry)
            .where(
                OutboxEntry.processed_at.is_(None),
                OutboxEntry.attempts < MAX_ATTEMPTS,
                OutboxEntry.available_at <= func.now(),
            )
            .order_by(OutboxEntry.available_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return await self._session.scalar(stmt)
```

## `app/outbox/dispatcher.py`

```python
# app/outbox/dispatcher.py
import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.message_bus import MessageBus
from app.outbox.repo import OutboxRepo


_log = structlog.get_logger(__name__)


async def dispatch_outbox(
    session_factory: async_sessionmaker[AsyncSession],
    bus: MessageBus,
    *,
    batch_size: int = 100,
) -> int:
    dispatched = 0
    for _ in range(batch_size):
        async with session_factory() as session, session.begin():
            entry = await OutboxRepo(session).claim_next()
            if entry is None:
                break
            try:
                await bus.publish(entry.to_event())
            except Exception as exc:
                _log.exception("outbox.dispatch.failed", entry_id=entry.id, attempt=entry.attempts + 1)
                entry.record_failure(exc)
            else:
                entry.mark_processed()
        dispatched += 1
    return dispatched


async def run_outbox_loop(
    session_factory: async_sessionmaker[AsyncSession],
    bus: MessageBus,
    *,
    poll_interval: float = 1.0,
) -> None:
    while True:
        if await dispatch_outbox(session_factory, bus) == 0:
            await asyncio.sleep(poll_interval)
```

`run_outbox_loop` sleeps only when a pass found nothing to do. A backlog drains at full speed, and an idle queue costs one cheap query per `poll_interval`.
