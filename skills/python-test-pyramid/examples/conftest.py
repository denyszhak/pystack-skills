from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.clients.openai import OpenAIClient
from app.config import AppConfig, DBConfig
from app.db import close_db_pool, init_db_pool
from app.setup import provide_app


pytest_plugins = [
    "tests.fixtures.models",
    "tests.fixtures.services",
    "tests.fixtures.clients",
    "tests.fixtures.repos",
]

# No `event_loop` fixture: pytest-asyncio 1.0 removed it. Fixtures and tests share
# one session-wide loop via asyncio_default_*_loop_scope in pyproject.toml.


@pytest.fixture(scope="session")
def config() -> AppConfig:
    base = AppConfig()
    name = base.db.NAME if base.db.NAME.endswith("_test") else f"{base.db.NAME}_test"
    return base.model_copy(update={"ENV": "test", "db": base.db.model_copy(update={"NAME": name})})


def _setup_test_database(engine: Engine, db_config: DBConfig) -> None:
    _teardown_test_database(engine, db_config)
    with engine.connect() as conn:
        conn.execute(text(
            f'CREATE DATABASE "{db_config.NAME}" '
            f'OWNER "{db_config.USER}" ENCODING \'utf-8\';'
        ))
    _run_db_migrations(db_config)


def _teardown_test_database(engine: Engine, db_config: DBConfig) -> None:
    if not db_config.NAME.endswith("_test"):
        raise RuntimeError(f"refusing to drop {db_config.NAME!r}: test database names must end in '_test'")
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_config.NAME}" WITH (FORCE);'))


def _run_db_migrations(db_config: DBConfig) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig
    alembic_cfg = AlembicConfig("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_config.sync_url().render_as_string(hide_password=False))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session")
def setup_database(config: AppConfig) -> Iterator[None]:
    bootstrap_url = config.db.sync_url().set(database="postgres")
    engine = create_engine(bootstrap_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    _setup_test_database(engine, config.db)
    yield
    _teardown_test_database(engine, config.db)
    engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def app(
    config: AppConfig,
    setup_database: None,
    openai_client: OpenAIClient,          # session-scoped, from tests/fixtures/clients.py
) -> AsyncIterator[FastAPI]:
    app = provide_app(config)
    # Skip lifespan; set app.state manually so fake clients stay fake.
    await init_db_pool(app, config.db)    # same pool + session factory as production
    app.state.llm_client = openai_client
    yield app
    await close_db_pool(app)


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with app.state.db_session_factory() as s:
        yield s
