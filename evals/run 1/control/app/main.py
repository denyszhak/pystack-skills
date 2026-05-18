from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import router
from app.config import get_settings
from app.database import create_database_schema
from app.errors import ApplicationError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    settings = get_settings()
    if settings.create_tables_on_startup:
        await create_database_schema()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="B2B Invoice Collection API", lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        request: Request, exc: ApplicationError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    return app


app = create_app()

