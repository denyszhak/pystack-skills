"""Canonical repo for the Order aggregate.

Takes session in constructor. Returns SA model instances.
YAGNI: only methods a service currently calls.
No commit or begin anywhere — the top-level service owns the transaction boundary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import UniqueViolationException
from app.models.order import Order, OrderNotFoundException


class OrderRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, order_id: UUID) -> Order | None:
        return await self._session.get(Order, order_id)

    async def get_or_raise(self, order_id: UUID) -> Order:
        order = await self.get(order_id)
        if order is None:
            raise OrderNotFoundException(order_id)
        return order

    async def add(self, order: Order) -> None:
        self._session.add(order)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise UniqueViolationException(f"order {order.id} already exists") from exc

    async def save(self, order: Order) -> None:
        await self._session.merge(order)

    async def list_for_customer(self, customer_id: UUID) -> AsyncIterator[Order]:
        stmt = select(Order).where(Order.customer_id == customer_id)
        result = await self._session.stream_scalars(stmt)
        async for order in result:
            yield order

    async def list_recent_high_value(
        self,
        *,
        since: datetime,
        min_total: Decimal,
    ) -> AsyncIterator[Order]:
        # Compute total in SQL via the join, not via Python `order.total`,
        # so we don't load every order to filter.
        from app.models.order import OrderLine
        subtotal = (OrderLine.quantity * OrderLine.unit_price).label("subtotal")
        totals = (
            select(OrderLine.order_id, func.sum(subtotal).label("total"))
            .group_by(OrderLine.order_id)
            .subquery()
        )
        stmt = (
            select(Order)
            .join(totals, totals.c.order_id == Order.id)
            .where(Order.placed_at >= since)
            .where(totals.c.total >= min_total)
        )
        result = await self._session.stream_scalars(stmt)
        async for order in result:
            yield order
