"""CorrelationIDMiddleware + logging_middleware.

CorrelationIDMiddleware sets the ContextVar so every log line in the request
includes correlation_id automatically. logging_middleware emits structured
start/end events.
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.common.logging import correlation_id_var


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        cid = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        token = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            correlation_id_var.reset(token)


_log = structlog.get_logger("app.request")


async def logging_middleware(request: Request, call_next) -> Response:
    started = time.perf_counter()
    _log.info("request.start", method=request.method, path=request.url.path)

    response = await call_next(request)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    _log.info(
        "request.end",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        elapsed_ms=elapsed_ms,
    )
    return response
