from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.db import get_session
from app.outbox.repo import OutboxRepo
from app.repos.customer import CustomerRepo
from app.repos.invoice import InvoiceRepo


def get_customer_repo(session: Annotated[AsyncSession, Depends(get_session)]) -> CustomerRepo:
    return CustomerRepo(session)


def get_invoice_repo(session: Annotated[AsyncSession, Depends(get_session)]) -> InvoiceRepo:
    return InvoiceRepo(session)


def get_outbox_repo(session: Annotated[AsyncSession, Depends(get_session)]) -> OutboxRepo:
    return OutboxRepo(session)
