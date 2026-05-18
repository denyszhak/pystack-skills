from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps.services import get_billing_service
from app.schemas.customer import CustomerCreate, CustomerGet
from app.services.billing import BillingService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_customer(
    cmd: CustomerCreate,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> CustomerGet:
    return await service.create_customer(cmd)
