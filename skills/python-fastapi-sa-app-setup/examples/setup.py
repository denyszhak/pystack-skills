from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api import system
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware.correlation import CorrelationIDMiddleware
from app.api.middleware.logging import logging_middleware
from app.api.v1 import provide_api_v1_router
from app.clients.llm import cleanup_llm_client, init_llm_client
from app.clients.stripe import cleanup_stripe_client, init_stripe_client
from app.common.logging import configure_logging
from app.config import AppConfig
from app.db import close_db_pool, init_db_pool


class ErrorSchema(BaseModel):
    errors: list[str]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config: AppConfig = app.state.config
    async with AsyncExitStack() as stack:
        await init_db_pool(app, config.db)
        stack.push_async_callback(close_db_pool, app)

        await init_stripe_client(app, config.stripe)
        stack.push_async_callback(cleanup_stripe_client, app)

        await init_llm_client(app, config)
        stack.push_async_callback(cleanup_llm_client, app)

        yield


def _add_middleware(app: FastAPI, config: AppConfig) -> None:
    if config.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.middleware("http")(logging_middleware)
    app.add_middleware(CorrelationIDMiddleware)


def _include_routers(app: FastAPI) -> None:
    app.include_router(system.router)
    app.include_router(provide_api_v1_router(), prefix="/api/v1")


def provide_app(config: AppConfig) -> FastAPI:
    configure_logging(env=config.ENV)
    app = FastAPI(
        title=config.NAME,
        debug=config.DEBUG,
        version=config.VERSION,
        lifespan=lifespan,
        responses={status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorSchema}},
    )
    app.state.config = config
    _add_middleware(app, config)
    register_exception_handlers(app)
    _include_routers(app)
    return app


app_config = AppConfig()
app = provide_app(app_config)
