from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.invoice import InvoiceEvent
from app.outbox.model import OutboxEntry


class OutboxRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_event(self, event: InvoiceEvent) -> None:
        self._session.add(OutboxEntry.from_event(event))
        await self._session.flush()

    async def list_unprocessed(self, *, limit: int) -> list[OutboxEntry]:
        stmt: Select[tuple[OutboxEntry]] = (
            select(OutboxEntry)
            .where(OutboxEntry.processed_at.is_(None))
            .order_by(OutboxEntry.created_at)
            .limit(limit)
        )
        entries = await self._session.scalars(stmt)
        return list(entries)
