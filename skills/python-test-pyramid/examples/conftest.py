"""Canonical tests/conftest.py.

Session-scoped: config, db setup, app (with manual app.state).
Function-scoped: client (httpx ASGITransport), session.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.config import AppConfig, DBConfig
from app.db import provide_async_db_pool
from app.setup import provide_app


pytest_plugins = [
    "tests.fixtures.models",
    "tests.fixtures.services",
    "tests.fixtures.clients",
    "tests.fixtures.repos",
]


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def config() -> AppConfig:
    return AppConfig()


def _setup_test_database(engine: Engine, db_config: DBConfig) -> None:
    _teardown_test_database(engine, db_config)
    with engine.connect() as conn:
        conn.execute(text(
            f'CREATE DATABASE {db_config.NAME} '
            f'OWNER "{db_config.USER}" ENCODING \'utf-8\';'
        ))
    _run_db_migrations(db_config)


def _teardown_test_database(engine: Engine, db_config: DBConfig) -> None:
    with engine.connect() as conn:
        conn.execute(text(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{db_config.NAME}'
              AND pid <> pg_backend_pid();
        """))
        conn.execute(text(f"DROP DATABASE IF EXISTS {db_config.NAME};"))


def _run_db_migrations(db_config: DBConfig) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig
    alembic_cfg = AlembicConfig("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", str(db_config.sync_url()))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session")
def setup_database(config: AppConfig) -> Iterator[None]:
    bootstrap_url = config.db.sync_url().set(database="postgres")
    engine = create_engine(bootstrap_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    _setup_test_database(engine, config.db)
    yield
    _teardown_test_database(engine, config.db)


@pytest_asyncio.fixture(scope="session")
async def app(
    config: AppConfig,
    setup_database: None,
    # client fixtures injected here from tests/fixtures/clients.py:
    # openai_client, stripe_client, ...
) -> FastAPI:
    app = provide_app(config)
    # Skip lifespan; set app.state manually so fake clients stay fake.
    app.state.db_pool = await provide_async_db_pool(config.db)
    app.state.db_session_factory = async_sessionmaker(
        app.state.db_pool, expire_on_commit=False,
    )
    # app.state.openai_client = openai_client   # populated by fixtures/clients.py
    return app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def session(app: FastAPI) -> AsyncSession:
    async with AsyncSession(app.state.db_pool, expire_on_commit=False) as s:
        yield s
