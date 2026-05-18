import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.common.exceptions import (
    AppException,
    ConflictException,
    ExternalServiceException,
    InvalidInputException,
    NotFoundException,
)

log = structlog.get_logger(__name__)


def _error_payload(
    exc: AppException | HTTPException | Exception,
) -> dict[str, list[dict[str, str]]]:
    if isinstance(exc, AppException):
        return {"errors": [{"code": exc.code, "message": str(exc)}]}
    return {"errors": [{"code": "http_error", "message": str(exc)}]}


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        log.error("http.error", status_code=exc.status_code, detail=exc.detail)
    else:
        log.warning("http.error", status_code=exc.status_code, detail=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"errors": [{"code": "http_error", "message": str(exc.detail)}]},
    )


async def validation_exception_handler(
    _: Request,
    exc: RequestValidationError | ValidationError,
) -> JSONResponse:
    log.warning("validation.error", errors=exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"errors": exc.errors()},
    )


async def invalid_input_exception_handler(_: Request, exc: InvalidInputException) -> JSONResponse:
    log.warning("invalid_input", error=str(exc), code=exc.code)
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=_error_payload(exc))


async def not_found_exception_handler(_: Request, exc: NotFoundException) -> JSONResponse:
    log.warning("not_found", error=str(exc), code=exc.code)
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=_error_payload(exc))


async def conflict_exception_handler(_: Request, exc: ConflictException) -> JSONResponse:
    log.warning("conflict", error=str(exc), code=exc.code)
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=_error_payload(exc))


async def external_service_exception_handler(
    _: Request,
    exc: ExternalServiceException,
) -> JSONResponse:
    log.warning("external_service.error", error=str(exc), code=exc.code)
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=_error_payload(exc))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, validation_exception_handler)
    app.add_exception_handler(InvalidInputException, invalid_input_exception_handler)
    app.add_exception_handler(NotFoundException, not_found_exception_handler)
    app.add_exception_handler(ConflictException, conflict_exception_handler)
    app.add_exception_handler(ExternalServiceException, external_service_exception_handler)
