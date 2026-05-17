from __future__ import annotations

from typing import Any

import httpx
from fastapi import status


class OpenAIMock:
    def __init__(self) -> None:
        self._chat_response: dict[str, Any] = {
            "choices": [{"message": {"role": "assistant", "content": "default"}}],
        }
        self._chat_status: int = status.HTTP_200_OK

    def set_chat_response(
        self,
        response: dict[str, Any],
        *,
        http_status: int = status.HTTP_200_OK,
    ) -> None:
        self._chat_response = response
        self._chat_status = http_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            return httpx.Response(self._chat_status, json=self._chat_response)
        return httpx.Response(
            status.HTTP_404_NOT_FOUND,
            json={"detail": f"unmocked: {request.method} {request.url.path}"},
        )
