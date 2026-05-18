from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api import get_email_provider, get_payment_provider
from app.clients import EmailProviderClient, PaymentProviderClient, PaymentProviderResult
from app.database import get_session
from app.errors import ExternalProviderError
from app.main import create_app
from app.models import Base, PaymentAttemptStatus


class FakePaymentProvider(PaymentProviderClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.raise_error = False
        self.status = PaymentAttemptStatus.SUCCEEDED

    async def collect_payment(self, **kwargs) -> PaymentProviderResult:
        self.calls.append(kwargs)
        if self.raise_error:
            raise ExternalProviderError(provider="payment", message="provider timeout")
        succeeded = self.status == PaymentAttemptStatus.SUCCEEDED
        return PaymentProviderResult(
            status=self.status,
            provider_payment_id="pay_test_123" if succeeded else None,
            error_code=None if succeeded else "card_declined",
            error_message=None if succeeded else "Card was declined.",
        )


class FakeEmailProvider(EmailProviderClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.raise_error = False

    async def send_invoice_issued(self, **kwargs) -> None:
        self.calls.append(kwargs)
        if self.raise_error:
            raise ExternalProviderError(provider="email", message="email provider unavailable")


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def api_client(
    db_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncClient, FakePaymentProvider, FakeEmailProvider]]:
    app = create_app()
    payment_provider = FakePaymentProvider()
    email_provider = FakeEmailProvider()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_payment_provider] = lambda: payment_provider
    app.dependency_overrides[get_email_provider] = lambda: email_provider

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, payment_provider, email_provider
