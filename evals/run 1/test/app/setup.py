import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from fastapi import FastAPI

from app.api.exception_handlers import register_exception_handlers
from app.api.middleware.correlation import CorrelationIDMiddleware
from app.api.middleware.logging import logging_middleware
from app.api.system import router as system_router
from app.api.v1 import provide_api_v1_router
from app.clients.email import cleanup_email_provider_client, init_email_provider_client
from app.clients.payment import cleanup_payment_provider_client, init_payment_provider_client
from app.common.logging import configure_logging
from app.config import AppConfig
from app.db import close_db_pool, init_db_pool
from app.handlers import build_message_bus
from app.outbox.dispatcher import run_outbox_loop


async def _cancel_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config: AppConfig = app.state.config
    async with AsyncExitStack() as stack:
        await init_db_pool(app, config.db)
        stack.push_async_callback(close_db_pool, app)

        await init_payment_provider_client(app, config.payment_provider)
        stack.push_async_callback(cleanup_payment_provider_client, app)

        await init_email_provider_client(app, config.email_provider)
        stack.push_async_callback(cleanup_email_provider_client, app)

        app.state.bus = build_message_bus(
            session_factory=app.state.db_session_factory,
            emailer=app.state.email_provider_client,
            swallow_handler_errors=False,
        )

        if config.outbox.ENABLED:
            outbox_task = asyncio.create_task(
                run_outbox_loop(
                    session_factory=app.state.db_session_factory,
                    bus=app.state.bus,
                    batch_size=config.outbox.BATCH_SIZE,
                    poll_interval_seconds=config.outbox.POLL_INTERVAL_SECONDS,
                )
            )
            stack.push_async_callback(_cancel_task, outbox_task)

        yield


def provide_app(config: AppConfig) -> FastAPI:
    configure_logging(env=config.ENV)
    app = FastAPI(
        title=config.NAME,
        version=config.VERSION,
        debug=config.DEBUG,
        lifespan=lifespan,
    )
    app.state.config = config
    _add_middleware(app)
    _register_exception_handlers(app)
    _include_routers(app)
    return app


def _add_middleware(app: FastAPI) -> None:
    app.middleware("http")(logging_middleware)
    app.add_middleware(CorrelationIDMiddleware)


def _register_exception_handlers(app: FastAPI) -> None:
    register_exception_handlers(app)


def _include_routers(app: FastAPI) -> None:
    app.include_router(system_router)
    app.include_router(provide_api_v1_router())


app_config = AppConfig()
app = provide_app(app_config)
