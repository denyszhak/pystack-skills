from __future__ import annotations

from datetime import UTC, datetime
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.common.exceptions import NotFoundException
from app.models.base import Base


class CustomerNotFoundException(NotFoundException):
    code = "customer_not_found"

    def __init__(self, customer_id: UUID) -> None:
        super().__init__(f"customer {customer_id} was not found")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)

    @classmethod
    def new(cls, *, name: str, email: str) -> Self:
        return cls(id=uuid4(), name=name, email=email)
