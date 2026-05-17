from __future__ import annotations

import httpx
from fastapi import FastAPI, status

from app.clients.base import BaseHTTPClient
from app.common.exceptions import (
    AppException,
    NotAuthenticatedException,
)
from app.config import OpenAIConfig
from app.schemas.llm import ChatMessage   # role + content; lives in app/schemas/llm.py


class RateLimitedException(AppException):
    pass


class OpenAIAuthException(NotAuthenticatedException):
    def __init__(self) -> None:
        super().__init__("openai api key is missing or invalid")


class OpenAIRateLimitedException(RateLimitedException):
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
                json={
                    "model": model or self._config.MODEL,
                    "messages": [m.model_dump() for m in messages],
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == status.HTTP_401_UNAUTHORIZED:
                raise OpenAIAuthException() from exc
            if exc.response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                raise OpenAIRateLimitedException() from exc
            raise
        return response.json()["choices"][0]["message"]["content"]


async def init_openai_client(app: FastAPI, config: OpenAIConfig) -> None:
    app.state.llm_client = OpenAIClient.from_config(config)


async def cleanup_openai_client(app: FastAPI) -> None:
    if hasattr(app.state, "llm_client"):
        await app.state.llm_client.close()
