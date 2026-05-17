from __future__ import annotations

from typing import Any, Literal, Self

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import BaseHTTPClientConfig


type HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


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

    async def _request(self, method: HTTPMethod, url: str, **kwargs: Any) -> httpx.Response:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._config.MAX_RETRIES),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        ):
            with attempt:
                response = await self._http.request(method, url, **kwargs)
                response.raise_for_status()
                return response
        raise RuntimeError("unreachable")
