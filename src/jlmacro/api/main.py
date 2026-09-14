"""FastAPI application entrypoint.

Phase 1/2 exposes read-only endpoints over the seeded instrument universe and PIT
market/macro data; Phase 3 adds computed macro regime snapshots; Phase 4 adds the
quantitative signal engine (trend/valuation/positioning/catalyst/composite score);
Phase 5 adds portfolio construction; Phase 6 adds the risk engine; Phase 7 adds
backtesting; Phase 8 adds the trade lifecycle; Phase 9 adds NAV/attribution;
Phase 10 adds paper execution; Phase 11 adds the ML research layer - so the
dashboard (and future integrations) have something real to consume. Phase 12 adds
optional API-key auth (`jlmacro.api.security`), off by default for local
development.
"""

from __future__ import annotations

from fastapi import FastAPI

from jlmacro.api.routers import (
    backtest,
    health,
    instruments,
    macro_data,
    market_data,
    ml,
    nav,
    portfolio,
    regime,
    risk,
    signals,
    trades,
)
from jlmacro.api.security import ApiKeyMiddleware
from jlmacro.config import get_settings
from jlmacro.utils.logging import configure_logging

configure_logging()

settings = get_settings()

app = FastAPI(
    title="JL Global Macro Investment Platform API",
    description="Research, risk and portfolio management API. Live trading is disabled by default.",
    version="0.1.0",
)

app.add_middleware(ApiKeyMiddleware)

app.include_router(health.router)
app.include_router(instruments.router)
app.include_router(market_data.router)
app.include_router(macro_data.router)
app.include_router(regime.router)
app.include_router(signals.router)
app.include_router(portfolio.router)
app.include_router(risk.router)
app.include_router(backtest.router)
app.include_router(trades.router)
app.include_router(nav.router)
app.include_router(ml.router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "JL Global Macro Investment Platform API",
        "environment": settings.jlmacro_env,
        "docs": "/docs",
    }
