from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.payment import PaymentProviderClient
from app.deps.clients import get_payment_provider_client
from app.deps.db import get_session
from app.deps.repos import get_customer_repo, get_invoice_repo, get_outbox_repo
from app.outbox.repo import OutboxRepo
from app.repos.customer import CustomerRepo
from app.repos.invoice import InvoiceRepo
from app.services.billing import BillingService


def get_billing_service(
    customers: Annotated[CustomerRepo, Depends(get_customer_repo)],
    invoices: Annotated[InvoiceRepo, Depends(get_invoice_repo)],
    outbox: Annotated[OutboxRepo, Depends(get_outbox_repo)],
    payment_provider: Annotated[PaymentProviderClient, Depends(get_payment_provider_client)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BillingService:
    return BillingService(
        customers=customers,
        invoices=invoices,
        outbox=outbox,
        payment_provider=payment_provider,
        session=session,
    )
