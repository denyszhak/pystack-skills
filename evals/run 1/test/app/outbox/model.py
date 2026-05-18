from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self
from uuid import UUID, uuid4

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base

if TYPE_CHECKING:
    from app.events.invoice import InvoiceEvent


class OutboxEntry(Base):
    __tablename__ = "outbox_entries"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(nullable=False, index=True)
    payload: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(default=None, index=True)
    error: Mapped[str | None] = mapped_column(default=None)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)

    @classmethod
    def from_event(cls, event: InvoiceEvent) -> Self:
        return cls(event_type=event.event_type, payload=event.to_payload())

    def mark_processed(self) -> None:
        self.processed_at = datetime.now(UTC)
        self.error = None

    def mark_failed(self, *, message: str) -> None:
        self.attempts += 1
        self.error = message
