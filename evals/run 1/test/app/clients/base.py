from typing import Any, Literal, Self

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import BaseHTTPClientConfig

HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
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
        retry_non_idempotent: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        should_retry = method == "GET" or retry_non_idempotent
        if not should_retry:
            return await self._send_once(method, url, **kwargs)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._config.MAX_RETRIES),
            wait=wait_exponential(multiplier=0.1, max=2),
            retry=retry_if_exception(_is_retryable_http_error),
            reraise=True,
        ):
            with attempt:
                return await self._send_once(method, url, **kwargs)
        raise RuntimeError("unreachable retry state")

    async def _send_once(self, method: HTTPMethod, url: str, **kwargs: Any) -> httpx.Response:
        response = await self._http.request(method, url, **kwargs)
        response.raise_for_status()
        return response
