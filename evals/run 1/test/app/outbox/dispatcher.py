import asyncio
from collections.abc import Mapping
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.message_bus import MessageBus
from app.events.invoice import InvoiceEvent, InvoiceIssued, InvoicePaid
from app.outbox.repo import OutboxRepo

log = structlog.get_logger(__name__)

_EVENT_TYPES: Final[Mapping[str, type[InvoiceIssued] | type[InvoicePaid]]] = {
    InvoiceIssued.event_type: InvoiceIssued,
    InvoicePaid.event_type: InvoicePaid,
}


def _event_from_entry(event_type: str, payload: dict[str, str]) -> InvoiceEvent:
    event_cls = _EVENT_TYPES.get(event_type)
    if event_cls is None:
        raise ValueError(f"unknown outbox event type: {event_type}")
    return event_cls.from_payload(payload)


async def dispatch_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    bus: MessageBus,
    batch_size: int,
) -> int:
    async with session_factory() as session, session.begin():
        outbox = OutboxRepo(session)
        entries = await outbox.list_unprocessed(limit=batch_size)
        for entry in entries:
            try:
                event = _event_from_entry(entry.event_type, entry.payload)
                await bus.publish(event)
                entry.mark_processed()
            except Exception as exc:
                log.exception("outbox.dispatch.failed", entry_id=entry.id)
                entry.mark_failed(message=str(exc))
        return len(entries)


async def run_outbox_loop(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    bus: MessageBus,
    batch_size: int,
    poll_interval_seconds: float,
) -> None:
    while True:
        await dispatch_once(session_factory=session_factory, bus=bus, batch_size=batch_size)
        await asyncio.sleep(poll_interval_seconds)
