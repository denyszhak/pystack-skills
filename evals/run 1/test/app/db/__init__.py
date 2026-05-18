from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import DBConfig
from app.models import Base
from app.outbox import model as outbox_model


async def init_db_pool(app: FastAPI, config: DBConfig) -> None:
    _ = outbox_model.OutboxEntry
    engine = create_async_engine(
        config.url,
        echo=config.ECHO,
        pool_size=config.POOL_SIZE,
        max_overflow=config.POOL_OVERFLOW,
        pool_recycle=config.POOL_RECYCLE,
    )
    if config.AUTO_CREATE_TABLES:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    app.state.db_pool = engine
    app.state.db_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def close_db_pool(app: FastAPI) -> None:
    if hasattr(app.state, "db_pool"):
        engine: AsyncEngine = app.state.db_pool
        await engine.dispose()


async def provide_async_db_pool(config: DBConfig) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(config.url, echo=config.ECHO)
    try:
        yield engine
    finally:
        await engine.dispose()


def provide_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
