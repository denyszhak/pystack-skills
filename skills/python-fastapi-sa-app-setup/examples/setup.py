"""Canonical app/setup.py — the spine of a FastAPI + SA service.

Lifespan opens app-lifetime resources (db pool, http clients) on app.state.
provide_app(config) is the test-friendly factory.
Module bottom creates the ASGI `app` for `uvicorn app.setup:app`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError

from app.api import system
from app.api.exception_handlers import (
    conflict_exception_handler,
    http_exception_handler,
    not_found_exception_handler,
    request_validation_exception_handler,
)
from app.api.middleware.correlation import CorrelationIDMiddleware
from app.api.middleware.logging import logging_middleware
from app.api.v1 import provide_api_v1_router
from app.clients.openai import cleanup_openai_client, init_openai_client
from app.common.exceptions import ConflictException, NotFoundException
from app.common.logging import configure_logging
from app.config import AppConfig
from app.db import close_db_pool, init_db_pool


class ErrorSchema(BaseModel):
    errors: list[str]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize resources in order; AsyncExitStack guarantees cleanup of any
    partially-initialized state if a later init raises.
    """
    config: AppConfig = app.state.config
    async with AsyncExitStack() as stack:
        await init_db_pool(app, config.db)
        stack.push_async_callback(close_db_pool, app)

        await init_openai_client(app, config.openai)
        stack.push_async_callback(cleanup_openai_client, app)

        yield


def _add_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(logging_middleware)
    app.add_middleware(CorrelationIDMiddleware)


def _register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(ValidationError, request_validation_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(NotFoundException, not_found_exception_handler)
    app.add_exception_handler(ConflictException, conflict_exception_handler)


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
        responses={status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorSchema}},
    )
    app.state.config = config
    _add_middleware(app)
    _register_exception_handlers(app)
    _include_routers(app)
    return app


app_config = AppConfig()
app = provide_app(app_config)
