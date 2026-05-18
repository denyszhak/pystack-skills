from decimal import Decimal
from uuid import UUID

import httpx
from fastapi import FastAPI, status

from app.clients.base import BaseHTTPClient
from app.common.exceptions import ExternalServiceException, RateLimitedException
from app.config import EmailProviderConfig


class EmailProviderException(ExternalServiceException):
    code = "email_provider_error"


class EmailProviderRateLimitedException(RateLimitedException):
    code = "email_provider_rate_limited"


class EmailProviderClient(BaseHTTPClient):
    async def send_invoice_issued(
        self,
        *,
        to: str,
        invoice_id: UUID,
        total: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> None:
        await self._send_email(
            "emails/invoice-issued",
            to=to,
            invoice_id=invoice_id,
            total=total,
            currency=currency,
            idempotency_key=idempotency_key,
        )

    async def send_invoice_paid(
        self,
        *,
        to: str,
        invoice_id: UUID,
        total: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> None:
        await self._send_email(
            "emails/invoice-paid",
            to=to,
            invoice_id=invoice_id,
            total=total,
            currency=currency,
            idempotency_key=idempotency_key,
        )

    async def _send_email(
        self,
        path: str,
        *,
        to: str,
        invoice_id: UUID,
        total: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> None:
        try:
            await self._request(
                "POST",
                path,
                retry_non_idempotent=True,
                headers={"Idempotency-Key": idempotency_key},
                json={
                    "to": to,
                    "invoice_id": str(invoice_id),
                    "total": str(total),
                    "currency": currency,
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                raise EmailProviderRateLimitedException("email provider rate limited") from exc
            raise EmailProviderException("email provider returned an error") from exc
        except httpx.HTTPError as exc:
            raise EmailProviderException("email provider request failed") from exc


async def init_email_provider_client(app: FastAPI, config: EmailProviderConfig) -> None:
    app.state.email_provider_client = EmailProviderClient.from_config(config)


async def cleanup_email_provider_client(app: FastAPI) -> None:
    if hasattr(app.state, "email_provider_client"):
        client: EmailProviderClient = app.state.email_provider_client
        await client.close()
