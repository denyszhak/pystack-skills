from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.stripe import StripeClient
from app.repos.order import OrderRepo
from app.schemas.order import (
    CancelOrderCommand,
    OrderGet,
    PlaceOrderCommand,
    RefundOrderCommand,
)


class CheckoutService:
    def __init__(
        self,
        *,
        orders: OrderRepo,
        stripe: StripeClient,
        session: AsyncSession,
    ) -> None:
        self._orders = orders
        self._stripe = stripe
        self._session = session

    async def place_order(self, cmd: PlaceOrderCommand) -> OrderGet:
        async with self._session.begin():
            order = cmd.to_new_order()
            order.place()
            await self._stripe.charge(
                amount=order.total,
                currency=order.currency,
                customer_id=order.customer_id,
            )
            await self._orders.add(order)
        return OrderGet.from_model(order)

    async def cancel_order(self, cmd: CancelOrderCommand) -> OrderGet:
        async with self._session.begin():
            order = await self._orders.get_or_raise(cmd.order_id)
            order.cancel(reason=cmd.reason)
        return OrderGet.from_model(order)

    async def refund_order(self, cmd: RefundOrderCommand) -> OrderGet:
        async with self._session.begin():
            order = await self._orders.get_or_raise(cmd.order_id)
            await self._stripe.refund(charge_id=cmd.charge_id, amount=cmd.amount)
            order.cancel(reason=f"refund: {cmd.reason}")
        return OrderGet.from_model(order)
