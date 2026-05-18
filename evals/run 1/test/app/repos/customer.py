from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import UniqueViolationException
from app.models.customer import Customer, CustomerNotFoundException


class CustomerRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, customer_id: UUID) -> Customer | None:
        return await self._session.get(Customer, customer_id)

    async def get_or_raise(self, customer_id: UUID) -> Customer:
        customer = await self.get(customer_id)
        if customer is None:
            raise CustomerNotFoundException(customer_id)
        return customer

    async def add(self, customer: Customer) -> None:
        self._session.add(customer)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise UniqueViolationException("customer email already exists") from exc
