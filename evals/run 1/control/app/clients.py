from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx
from pydantic import AnyHttpUrl

from app.errors import ExternalProviderError
from app.models import PaymentAttemptStatus


@dataclass(frozen=True, slots=True)
class PaymentProviderResult:
    status: PaymentAttemptStatus
    provider_payment_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class PaymentProviderClient(Protocol):
    async def collect_payment(
        self,
        *,
        invoice_id: uuid.UUID,
        amount: Decimal,
        payment_method_token: str,
        idempotency_key: str,
    ) -> PaymentProviderResult:
        pass


class EmailProviderClient(Protocol):
    async def send_invoice_issued(
        self,
        *,
        invoice_id: uuid.UUID,
        customer_id: uuid.UUID,
        total: Decimal,
    ) -> None:
        pass


class HttpPaymentProviderClient:
    def __init__(self, base_url: AnyHttpUrl, timeout_seconds: float) -> None:
        self._base_url = str(base_url).rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def collect_payment(
        self,
        *,
        invoice_id: uuid.UUID,
        amount: Decimal,
        payment_method_token: str,
        idempotency_key: str,
    ) -> PaymentProviderResult:
        payload = {
            "invoice_id": str(invoice_id),
            "amount": str(amount),
            "payment_method_token": payment_method_token,
        }
        headers = {"Idempotency-Key": idempotency_key}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout_seconds
            ) as client:
                response = await client.post("/payments", json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExternalProviderError(
                provider="payment",
                message=f"payment provider returned HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalProviderError(provider="payment", message=str(exc)) from exc

        data = response.json()
        try:
            status = PaymentAttemptStatus(data.get("status", PaymentAttemptStatus.FAILED.value))
        except ValueError as exc:
            raise ExternalProviderError(
                provider="payment",
                message="payment provider returned an unknown payment status",
            ) from exc
        return PaymentProviderResult(
            status=status,
            provider_payment_id=data.get("provider_payment_id"),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
        )


class HttpEmailProviderClient:
    def __init__(self, base_url: AnyHttpUrl, timeout_seconds: float) -> None:
        self._base_url = str(base_url).rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def send_invoice_issued(
        self,
        *,
        invoice_id: uuid.UUID,
        customer_id: uuid.UUID,
        total: Decimal,
    ) -> None:
        payload = {
            "invoice_id": str(invoice_id),
            "customer_id": str(customer_id),
            "total": str(total),
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout_seconds
            ) as client:
                response = await client.post("/invoice-issued", json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExternalProviderError(
                provider="email",
                message=f"email provider returned HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalProviderError(provider="email", message=str(exc)) from exc
