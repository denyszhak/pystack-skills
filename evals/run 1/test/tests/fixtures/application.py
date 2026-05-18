import os
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.clients.email import EmailProviderClient
from app.clients.payment import PaymentProviderClient
from app.config import AppConfig, DBConfig
from app.handlers import build_message_bus
from app.models import Base
from app.outbox import model as outbox_model
from app.setup import provide_app
from tests.doubles.email import EmailProviderMock
from tests.doubles.payment import PaymentProviderMock


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url is None:
        pytest.skip("TEST_DATABASE_URL is required for Postgres-backed API tests")
    return url


@pytest.fixture
async def app(
    test_database_url: str,
    payment_mock: PaymentProviderMock,
    email_mock: EmailProviderMock,
) -> AsyncIterator[FastAPI]:
    config = AppConfig(
        ENV="test",
        db=DBConfig(URL=test_database_url),
    )
    application = provide_app(config)
    engine = create_async_engine(config.db.url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    _ = outbox_model.OutboxEntry

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    payment_http = httpx.AsyncClient(
        transport=httpx.MockTransport(payment_mock),
        base_url="https://payments.test/",
    )
    email_http = httpx.AsyncClient(
        transport=httpx.MockTransport(email_mock),
        base_url="https://email.test/",
    )
    payment_client = PaymentProviderClient(
        http=payment_http,
        config=config.payment_provider,
    )
    email_client = EmailProviderClient(
        http=email_http,
        config=config.email_provider,
    )

    application.state.db_pool = engine
    application.state.db_session_factory = session_factory
    application.state.payment_provider_client = payment_client
    application.state.email_provider_client = email_client
    application.state.bus = build_message_bus(
        session_factory=session_factory,
        emailer=email_client,
        swallow_handler_errors=False,
    )

    try:
        yield application
    finally:
        await payment_client.close()
        await email_client.close()
        await engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as test_client:
        yield test_client


@pytest.fixture
async def session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = app.state.db_session_factory
    async with factory() as db_session:
        yield db_session
