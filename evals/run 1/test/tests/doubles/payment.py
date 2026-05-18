from typing import Any

import httpx
from fastapi import status


class PaymentProviderMock:
    def __init__(self) -> None:
        self._status_code = status.HTTP_200_OK
        self._response: dict[str, Any] = {"payment_id": "pay_test", "status": "succeeded"}
        self.requests: list[httpx.Request] = []

    def set_collect_response(
        self,
        response: dict[str, Any],
        *,
        status_code: int = status.HTTP_200_OK,
    ) -> None:
        self._response = response
        self._status_code = status_code

    @property
    def collect_count(self) -> int:
        return len(
            [
                request
                for request in self.requests
                if request.method == "POST" and request.url.path == "/payments/collect"
            ]
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST" and request.url.path == "/payments/collect":
            return httpx.Response(self._status_code, json=self._response)
        return httpx.Response(status.HTTP_404_NOT_FOUND, json={"detail": "unmocked endpoint"})
