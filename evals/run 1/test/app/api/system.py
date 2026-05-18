from fastapi import APIRouter, Request

from app.config import AppConfig

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/version")
async def version(request: Request) -> dict[str, str]:
    config: AppConfig = request.app.state.config
    return {"version": config.VERSION}
