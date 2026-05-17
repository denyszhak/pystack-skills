from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from fastapi import FastAPI

from app.clients.anthropic import AnthropicClient
from app.clients.openai import OpenAIClient
from app.config import AppConfig
from app.schemas.llm import ChatMessage


class LLMClient(Protocol):
    async def chat(self, messages: list[ChatMessage], *, model: str | None = None) -> str: ...
    async def close(self) -> None: ...


type LLMBuilder = Callable[[AppConfig], LLMClient]


_BUILDERS: dict[str, LLMBuilder] = {
    "openai":    lambda c: OpenAIClient.from_config(c.openai),
    "anthropic": lambda c: AnthropicClient.from_config(c.anthropic),
    # add more providers here — services don't change
}


async def init_llm_client(app: FastAPI, config: AppConfig) -> None:
    try:
        build = _BUILDERS[config.llm.PROVIDER]
    except KeyError:
        raise ValueError(f"unknown LLM provider: {config.llm.PROVIDER}")
    app.state.llm_client = build(config)


async def cleanup_llm_client(app: FastAPI) -> None:
    if hasattr(app.state, "llm_client"):
        await app.state.llm_client.close()


# In app/deps/clients.py:
#
#   def get_llm_client(request: Request) -> LLMClient:
#       return request.app.state.llm_client
#
# Services depend on LLMClient (the Protocol) via Depends(get_llm_client).
# Swapping OpenAI ↔ Anthropic is one env var change at deploy time.
