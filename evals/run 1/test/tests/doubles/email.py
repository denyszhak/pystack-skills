import httpx
from fastapi import status


class EmailProviderMock:
    def __init__(self) -> None:
        self._status_code = status.HTTP_202_ACCEPTED
        self.requests: list[httpx.Request] = []

    def set_status(self, status_code: int) -> None:
        self._status_code = status_code

    @property
    def sent_paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST" and request.url.path in {
            "/emails/invoice-issued",
            "/emails/invoice-paid",
        }:
            return httpx.Response(self._status_code, json={"status": "accepted"})
        return httpx.Response(status.HTTP_404_NOT_FOUND, json={"detail": "unmocked endpoint"})
