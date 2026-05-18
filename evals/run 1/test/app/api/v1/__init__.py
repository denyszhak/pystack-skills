from fastapi import APIRouter

from app.api.v1.customer import router as customer_router
from app.api.v1.invoice import router as invoice_router


def provide_api_v1_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(customer_router)
    router.include_router(invoice_router)
    return router
