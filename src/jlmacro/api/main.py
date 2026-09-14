"""FastAPI application entrypoint.

Phase 1/2 exposes read-only endpoints over the seeded instrument universe, PIT market/
macro data, and (Phase 3) computed macro regime snapshots, so the dashboard (and future
integrations) have something real to consume. Portfolio/risk/execution endpoints are
added in later phases behind the same app.
"""

from __future__ import annotations

from fastapi import FastAPI

from jlmacro.api.routers import health, instruments, macro_data, market_data, regime
from jlmacro.config import get_settings
from jlmacro.utils.logging import configure_logging

configure_logging()

settings = get_settings()

app = FastAPI(
    title="JL Global Macro Investment Platform API",
    description="Research, risk and portfolio management API. Live trading is disabled by default.",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(instruments.router)
app.include_router(market_data.router)
app.include_router(macro_data.router)
app.include_router(regime.router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "JL Global Macro Investment Platform API",
        "environment": settings.jlmacro_env,
        "docs": "/docs",
    }
