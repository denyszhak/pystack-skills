from __future__ import annotations

import asyncio
from typing import Final

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.common.exceptions import AsyncDBPoolProvisionException
from app.config import DBConfig

_HEALTHCHECK: Final = text("SELECT 1;")


async def provide_async_db_pool(
    config: DBConfig,
    *,
    max_retries: int = 3,
    retry_interval: float = 2.0,
) -> AsyncEngine:
    for attempt in range(max_retries + 1):
        pool = create_async_engine(
            config.url,
            echo=config.ECHO,
            pool_size=config.POOL_SIZE,
            max_overflow=config.POOL_OVERFLOW,
            pool_recycle=config.POOL_RECYCLE,
            pool_pre_ping=True,
        )
        try:
            async with pool.begin() as conn:
                await conn.execute(_HEALTHCHECK)
            return pool
        except Exception as exc:
            await pool.dispose()                        # don't leak a pool per failed attempt
            if attempt < max_retries:
                await asyncio.sleep(retry_interval)
                continue
            raise AsyncDBPoolProvisionException(
                f"failed to connect to db at {config.PATH}",
            ) from exc
    raise AssertionError("unreachable: the last attempt returns or raises")


async def init_db_pool(app: FastAPI, config: DBConfig) -> None:
    pool = await provide_async_db_pool(config)
    app.state.db_pool = pool
    app.state.db_session_factory = async_sessionmaker(pool, expire_on_commit=False)


async def close_db_pool(app: FastAPI) -> None:
    if hasattr(app.state, "db_pool"):
        await app.state.db_pool.dispose()
