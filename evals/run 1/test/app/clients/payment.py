from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

import httpx
from fastapi import FastAPI, status
from pydantic import BaseModel, ConfigDict

from app.clients.base import BaseHTTPClient
from app.common.exceptions import ExternalServiceException, RateLimitedException
from app.config import PaymentProviderConfig


class PaymentProviderException(ExternalServiceException):
    code = "payment_provider_error"


class PaymentProviderRejectedException(ExternalServiceException):
    code = "payment_provider_rejected"


class PaymentProviderRateLimitedException(RateLimitedException):
    code = "payment_provider_rate_limited"


class PaymentProviderResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    payment_id: str | None = None
    status: Literal["succeeded", "failed"]
    error_message: str | None = None


class PaymentProviderResult(BaseModel):
    provider_payment_id: str | None
    succeeded: bool
    error_message: str | None = None

    @classmethod
    def from_provider(cls, response: PaymentProviderResponse) -> Self:
        return cls(
            provider_payment_id=response.payment_id,
            succeeded=response.status == "succeeded",
            error_message=response.error_message,
        )


class PaymentProviderClient(BaseHTTPClient):
    async def collect_payment(
        self,
        *,
        invoice_id: UUID,
        amount: Decimal,
        currency: str,
        payment_method_token: str,
        idempotency_key: str,
    ) -> PaymentProviderResult:
        try:
            response = await self._request(
                "POST",
                "payments/collect",
                retry_non_idempotent=True,
                headers={"Idempotency-Key": idempotency_key},
                json={
                    "invoice_id": str(invoice_id),
                    "amount": str(amount),
                    "currency": currency,
                    "payment_method_token": payment_method_token,
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                raise PaymentProviderRateLimitedException("payment provider rate limited") from exc
            if status.HTTP_400_BAD_REQUEST <= exc.response.status_code < 500:
                raise PaymentProviderRejectedException(
                    "payment provider rejected the request"
                ) from exc
            raise PaymentProviderException("payment provider returned an error") from exc
        except httpx.HTTPError as exc:
            raise PaymentProviderException("payment provider request failed") from exc

        provider_response = PaymentProviderResponse.model_validate(response.json())
        return PaymentProviderResult.from_provider(provider_response)


async def init_payment_provider_client(app: FastAPI, config: PaymentProviderConfig) -> None:
    app.state.payment_provider_client = PaymentProviderClient.from_config(config)


async def cleanup_payment_provider_client(app: FastAPI) -> None:
    if hasattr(app.state, "payment_provider_client"):
        client: PaymentProviderClient = app.state.payment_provider_client
        await client.close()
