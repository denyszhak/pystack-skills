from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import (
    EmailProviderClient,
    HttpEmailProviderClient,
    HttpPaymentProviderClient,
    PaymentProviderClient,
)
from app.config import Settings, get_settings
from app.database import get_session
from app.schemas import (
    CustomerCreate,
    CustomerRead,
    InvoiceCreate,
    InvoiceLineCreate,
    InvoiceRead,
    InvoiceTotals,
    PaymentAttemptCreate,
    PaymentAttemptRead,
)
from app.services import InvoiceCollectionService

router = APIRouter()


def get_payment_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaymentProviderClient:
    return HttpPaymentProviderClient(
        settings.payment_provider_base_url,
        settings.external_http_timeout_seconds,
    )


def get_email_provider(settings: Annotated[Settings, Depends(get_settings)]) -> EmailProviderClient:
    return HttpEmailProviderClient(
        settings.email_provider_base_url,
        settings.external_http_timeout_seconds,
    )


def get_invoice_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    payment_provider: Annotated[PaymentProviderClient, Depends(get_payment_provider)],
    email_provider: Annotated[EmailProviderClient, Depends(get_email_provider)],
) -> InvoiceCollectionService:
    return InvoiceCollectionService(session, payment_provider, email_provider)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    service: Annotated[InvoiceCollectionService, Depends(get_invoice_service)],
) -> CustomerRead:
    return await service.create_customer(payload)


@router.post(
    "/customers/{customer_id}/invoices",
    response_model=InvoiceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice(
    customer_id: uuid.UUID,
    service: Annotated[InvoiceCollectionService, Depends(get_invoice_service)],
    payload: InvoiceCreate | None = None,
) -> InvoiceRead:
    return await service.create_invoice(customer_id, payload)


@router.get("/invoices/{invoice_id}", response_model=InvoiceRead)
async def get_invoice(
    invoice_id: uuid.UUID,
    service: Annotated[InvoiceCollectionService, Depends(get_invoice_service)],
) -> InvoiceRead:
    return await service.get_invoice(invoice_id)


@router.get("/invoices/{invoice_id}/total", response_model=InvoiceTotals)
async def calculate_invoice_total(
    invoice_id: uuid.UUID,
    service: Annotated[InvoiceCollectionService, Depends(get_invoice_service)],
) -> InvoiceTotals:
    return await service.calculate_invoice_total(invoice_id)


@router.post("/invoices/{invoice_id}/lines", response_model=InvoiceRead)
async def add_invoice_line(
    invoice_id: uuid.UUID,
    payload: InvoiceLineCreate,
    response: Response,
    service: Annotated[InvoiceCollectionService, Depends(get_invoice_service)],
) -> InvoiceRead:
    response.status_code = status.HTTP_201_CREATED
    return await service.add_invoice_line(invoice_id, payload)


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceRead)
async def issue_invoice(
    invoice_id: uuid.UUID,
    service: Annotated[InvoiceCollectionService, Depends(get_invoice_service)],
) -> InvoiceRead:
    return await service.issue_invoice(invoice_id)


@router.post("/invoices/{invoice_id}/payment-attempts", response_model=PaymentAttemptRead)
async def collect_payment(
    invoice_id: uuid.UUID,
    payload: PaymentAttemptCreate,
    idempotency_key: Annotated[str, Header(min_length=1, alias="Idempotency-Key")],
    service: Annotated[InvoiceCollectionService, Depends(get_invoice_service)],
) -> PaymentAttemptRead:
    return await service.collect_payment(invoice_id, payload, idempotency_key)
