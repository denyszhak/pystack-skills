from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.deps.services import get_billing_service
from app.schemas.invoice import (
    AddInvoiceLineCommand,
    CollectPaymentCommand,
    InvoiceCreate,
    InvoiceGet,
    InvoiceTotalGet,
    PaymentCollectionGet,
)
from app.services.billing import BillingService

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_invoice(
    cmd: InvoiceCreate,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> InvoiceGet:
    return await service.create_invoice(cmd)


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: UUID,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> InvoiceGet:
    return await service.get_invoice(invoice_id)


@router.post("/{invoice_id}/lines")
async def add_invoice_line(
    invoice_id: UUID,
    cmd: AddInvoiceLineCommand,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> InvoiceGet:
    return await service.add_invoice_line(invoice_id, cmd)


@router.get("/{invoice_id}/total")
async def get_invoice_total(
    invoice_id: UUID,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> InvoiceTotalGet:
    return await service.get_invoice_total(invoice_id)


@router.post("/{invoice_id}/issue")
async def issue_invoice(
    invoice_id: UUID,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> InvoiceGet:
    return await service.issue_invoice(invoice_id)


@router.post("/{invoice_id}/payment-attempts")
async def collect_payment(
    invoice_id: UUID,
    cmd: CollectPaymentCommand,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> PaymentCollectionGet:
    return await service.collect_payment(invoice_id, cmd)
