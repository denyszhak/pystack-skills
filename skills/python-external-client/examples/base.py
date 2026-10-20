from __future__ import annotations

from typing import Any, Final, Literal, Self

import httpx
from fastapi import status
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import BaseHTTPClientConfig


type HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == status.HTTP_429_TOO_MANY_REQUESTS or code >= status.HTTP_500_INTERNAL_SERVER_ERROR
    return False


class BaseHTTPClient:
    def __init__(self, *, http: httpx.AsyncClient, config: BaseHTTPClientConfig) -> None:
        self._http = http
        self._config = config

    @classmethod
    def from_config(cls, config: BaseHTTPClientConfig) -> Self:
        http = httpx.AsyncClient(
            base_url=config.BASE_URL,
            timeout=config.TIMEOUT,
            limits=httpx.Limits(
                max_keepalive_connections=config.KEEP_ALIVE_CONNECTIONS,
                max_connections=config.MAX_CONNECTIONS,
            ),
            headers=config.auth_headers(),
        )
        return cls(http=http, config=config)

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: HTTPMethod,
        url: str,
        *,
        retry: bool | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        # retry=None: only safe methods are retried. Pass retry=True for a request
        # you know is safe to repeat (idempotency key, or no side effects).
        retrying = method in _SAFE_METHODS if retry is None else retry
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(1 + (self._config.MAX_RETRIES if retrying else 0)),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception(_is_transient),
            reraise=True,
        ):
            with attempt:
                response = await self._http.request(method, url, **kwargs)
                response.raise_for_status()
                return response
        raise AssertionError("unreachable: AsyncRetrying either returns or reraises")
