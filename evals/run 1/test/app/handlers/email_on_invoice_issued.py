from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.email import EmailProviderClient
from app.events.invoice import InvoiceIssued
from app.repos.customer import CustomerRepo


def make_email_on_invoice_issued_handler(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    emailer: EmailProviderClient,
):
    async def email_on_invoice_issued(event: InvoiceIssued) -> None:
        async with session_factory() as session:
            customers = CustomerRepo(session)
            customer = await customers.get_or_raise(event.customer_id)

        await emailer.send_invoice_issued(
            to=customer.email,
            invoice_id=event.invoice_id,
            total=event.total,
            currency=event.currency,
            idempotency_key=f"invoice-issued:{event.invoice_id}",
        )

    return email_on_invoice_issued
