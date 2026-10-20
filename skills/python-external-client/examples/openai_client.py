from __future__ import annotations

import httpx
from fastapi import FastAPI, status

from app.clients.base import BaseHTTPClient
from app.common.exceptions import UpstreamException, UpstreamUnavailableException
from app.config import OpenAIConfig
from app.schemas.llm import ChatMessage   # role + content; lives in app/schemas/llm.py


class OpenAIException(UpstreamException):
    def __init__(self, detail: str = "openai request failed") -> None:
        super().__init__(detail)

    @classmethod
    def from_http_error(cls, exc: httpx.HTTPError) -> OpenAIException:
        if not isinstance(exc, httpx.HTTPStatusError):
            return OpenAIUnavailableException(f"openai unreachable: {exc!r}")
        match exc.response.status_code:
            case status.HTTP_401_UNAUTHORIZED | status.HTTP_403_FORBIDDEN:
                return OpenAIAuthException()
            case status.HTTP_429_TOO_MANY_REQUESTS:
                return OpenAIRateLimitedException()
            case code if code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
                return OpenAIUnavailableException(f"openai returned {code}")
            case code:
                return OpenAIException(f"openai returned {code}")


class OpenAIAuthException(OpenAIException):
    def __init__(self) -> None:
        super().__init__("openai rejected our api key")


class OpenAIUnavailableException(OpenAIException, UpstreamUnavailableException):
    def __init__(self, detail: str = "openai is unavailable") -> None:
        super().__init__(detail)


class OpenAIRateLimitedException(OpenAIUnavailableException):
    def __init__(self) -> None:
        super().__init__("openai rate limit exceeded")


class OpenAIClient(BaseHTTPClient):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> str:
        try:
            response = await self._request(
                "POST",
                "/v1/chat/completions",
                retry=True,     # a completion has no side effects beyond cost: safe to repeat
                json={
                    "model": model or self._config.MODEL,
                    "messages": [m.model_dump() for m in messages],
                },
            )
        except httpx.HTTPError as exc:
            raise OpenAIException.from_http_error(exc) from exc
        return response.json()["choices"][0]["message"]["content"]


async def init_openai_client(app: FastAPI, config: OpenAIConfig) -> None:
    app.state.llm_client = OpenAIClient.from_config(config)


async def cleanup_openai_client(app: FastAPI) -> None:
    if hasattr(app.state, "llm_client"):
        await app.state.llm_client.close()
