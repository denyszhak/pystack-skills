import time
from collections.abc import Awaitable, Callable

import structlog
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger("app.request")


async def logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    started = time.perf_counter()
    log.info("request.start", method=request.method, path=request.url.path)
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    log.info(
        "request.end",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        elapsed_ms=elapsed_ms,
    )
    return response
