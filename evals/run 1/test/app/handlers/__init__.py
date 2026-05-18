from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.email import EmailProviderClient
from app.common.message_bus import MessageBus
from app.events.invoice import InvoiceIssued, InvoicePaid
from app.handlers.email_on_invoice_issued import make_email_on_invoice_issued_handler
from app.handlers.email_on_invoice_paid import make_email_on_invoice_paid_handler


def build_message_bus(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    emailer: EmailProviderClient,
    swallow_handler_errors: bool = False,
) -> MessageBus:
    bus = MessageBus(swallow_handler_errors=swallow_handler_errors)
    bus.subscribe(
        InvoiceIssued,
        make_email_on_invoice_issued_handler(session_factory=session_factory, emailer=emailer),
    )
    bus.subscribe(
        InvoicePaid,
        make_email_on_invoice_paid_handler(session_factory=session_factory, emailer=emailer),
    )
    return bus
