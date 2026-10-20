from __future__ import annotations

from typing import Any

import httpx
from fastapi import status


_DEFAULT_CHAT_RESPONSE: dict[str, Any] = {
    "choices": [{"message": {"role": "assistant", "content": "default"}}],
}


class OpenAIMock:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._chat_responses: list[tuple[int, dict[str, Any]]] = []

    def reset(self) -> None:
        self.requests.clear()
        self._chat_responses.clear()

    def set_chat_response(
        self,
        response: dict[str, Any],
        *,
        http_status: int = status.HTTP_200_OK,
    ) -> None:
        self._chat_responses = [(http_status, response)]

    def queue_chat_responses(self, *responses: tuple[int, dict[str, Any]]) -> None:
        self._chat_responses = list(responses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            if not self._chat_responses:
                return httpx.Response(status.HTTP_200_OK, json=_DEFAULT_CHAT_RESPONSE)
            # Queued responses are served in order; the last one repeats.
            http_status, body = self._chat_responses[0]
            if len(self._chat_responses) > 1:
                self._chat_responses.pop(0)
            return httpx.Response(http_status, json=body)
        return httpx.Response(
            status.HTTP_404_NOT_FOUND,
            json={"detail": f"unmocked: {request.method} {request.url.path}"},
        )
