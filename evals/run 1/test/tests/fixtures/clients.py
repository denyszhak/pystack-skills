import httpx
import pytest

from app.clients.email import EmailProviderClient
from app.clients.payment import PaymentProviderClient
from app.config import EmailProviderConfig, PaymentProviderConfig
from tests.doubles.email import EmailProviderMock
from tests.doubles.payment import PaymentProviderMock


@pytest.fixture
def payment_mock() -> PaymentProviderMock:
    return PaymentProviderMock()


@pytest.fixture
def email_mock() -> EmailProviderMock:
    return EmailProviderMock()


@pytest.fixture
async def payment_provider_client(payment_mock: PaymentProviderMock) -> PaymentProviderClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(payment_mock),
        base_url="https://payments.test/",
    )
    client = PaymentProviderClient(
        http=http,
        config=PaymentProviderConfig(BASE_URL="https://payments.test/", MAX_RETRIES=1),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def email_provider_client(email_mock: EmailProviderMock) -> EmailProviderClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(email_mock),
        base_url="https://email.test/",
    )
    client = EmailProviderClient(
        http=http,
        config=EmailProviderConfig(BASE_URL="https://email.test/", MAX_RETRIES=1),
    )
    try:
        yield client
    finally:
        await client.close()
