"""NAV and attribution endpoints (jlmacro.nav, jlmacro.attribution, Phase 9): NAV,
high-water mark, drawdown and performance fee, computed on demand from the Trade rows
Phase 8 persists (never a separately-maintained ledger - see jlmacro.nav.engine's
module docstring), plus a P&L attribution breakdown of the same total.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import AttributionOut, NAVHistoryOut, NAVOut
from jlmacro.attribution.pnl import GroupBy, compute_pnl_attribution
from jlmacro.config import load_yaml_config
from jlmacro.nav.engine import drawdown_series, high_water_mark_series, nav_history
from jlmacro.nav.fees import compute_performance_fee, fees_config

router = APIRouter(prefix="/nav", tags=["nav"])


def _default_start() -> dt.date:
    return dt.date.fromisoformat(load_yaml_config("settings")["fund"]["inception_date"])


@router.get("", response_model=NAVOut)
def get_nav(
    portfolio_id: int,
    as_of: dt.date | None = Query(default=None, description="Defaults to today"),
    start: dt.date | None = Query(
        default=None, description="Defaults to the fund's inception date (config/settings.yaml)"
    ),
    starting_capital: float | None = Query(
        default=None, description="Defaults to config/fees.yaml"
    ),
    db: Session = Depends(get_db),
) -> NAVOut:
    as_of = as_of or dt.datetime.now(dt.UTC).date()
    start = start or _default_start()
    config = fees_config()
    starting_capital = (
        starting_capital if starting_capital is not None else config["starting_capital"]
    )

    series = nav_history(
        db, portfolio_id, start=start, end=as_of, starting_capital=starting_capital
    )
    nav_gross = float(series.iloc[-1])
    hwm = float(high_water_mark_series(series).iloc[-1])
    drawdown = float(drawdown_series(series).iloc[-1])
    fee_result = compute_performance_fee(
        nav_gross, hwm, performance_fee_pct=config["performance_fee_pct"]
    )

    return NAVOut(
        portfolio_id=portfolio_id,
        as_of=as_of,
        start=start,
        starting_capital=starting_capital,
        nav_gross=nav_gross,
        high_water_mark=hwm,
        drawdown=drawdown,
        performance_fee_accrued=fee_result.performance_fee_accrued,
        nav_net=fee_result.nav_net,
    )


@router.get("/history", response_model=NAVHistoryOut)
def get_nav_history(
    portfolio_id: int,
    start: dt.date | None = Query(default=None),
    end: dt.date | None = Query(default=None, description="Defaults to today"),
    frequency_days: int = Query(default=1, ge=1),
    starting_capital: float | None = Query(default=None),
    db: Session = Depends(get_db),
) -> NAVHistoryOut:
    start = start or _default_start()
    end = end or dt.datetime.now(dt.UTC).date()
    starting_capital = (
        starting_capital if starting_capital is not None else fees_config()["starting_capital"]
    )

    series = nav_history(
        db,
        portfolio_id,
        start=start,
        end=end,
        starting_capital=starting_capital,
        frequency_days=frequency_days,
    )
    return NAVHistoryOut(
        portfolio_id=portfolio_id,
        start=start,
        end=end,
        starting_capital=starting_capital,
        nav={d.isoformat(): float(v) for d, v in series.items()},
    )


@router.get("/attribution", response_model=AttributionOut)
def get_attribution(
    portfolio_id: int,
    as_of: dt.date | None = Query(default=None, description="Defaults to today"),
    group_by: GroupBy = Query(default="symbol"),
    db: Session = Depends(get_db),
) -> AttributionOut:
    as_of = as_of or dt.datetime.now(dt.UTC).date()
    breakdown = compute_pnl_attribution(db, portfolio_id, as_of=as_of, group_by=group_by)
    return AttributionOut(
        portfolio_id=portfolio_id, as_of=as_of, group_by=group_by, breakdown=breakdown
    )
