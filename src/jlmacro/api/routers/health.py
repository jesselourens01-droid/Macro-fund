from __future__ import annotations

from fastapi import APIRouter

from jlmacro.api.schemas import HealthOut
from jlmacro.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    settings = get_settings()
    return HealthOut(
        status="ok",
        environment=settings.jlmacro_env,
        live_trading_enabled=settings.jlmacro_live_trading_enabled,
    )
