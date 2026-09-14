"""Risk engine endpoints (jlmacro.risk, Phase 6): VaR/Expected Shortfall, hypothetical
and historical stress testing, and the drawdown governor.

Per the platform spec, this is the layer with actual authority over risk - Phase 5's
portfolio construction/sizing produces proposals; this reports the risk those
proposals actually carry, and (via the drawdown governor) how much risk budget is
currently available at all. Nothing here writes to a database - there is no persisted
position (Phase 8) or NAV history (Phase 9) yet, so every endpoint takes the weights,
NAV and current drawdown it needs explicitly.
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import (
    DrawdownGovernorOut,
    HistoricalStressOut,
    HistoricalStressRequest,
    HypotheticalStressOut,
    HypotheticalStressRequest,
    VaROut,
    VaRRequest,
)
from jlmacro.risk.drawdown import (
    apply_drawdown_governor,
    is_defensive_mode,
    risk_budget_fraction_for_drawdown,
)
from jlmacro.risk.stress import apply_historical_scenario, apply_hypothetical_scenario
from jlmacro.risk.var import compute_all_var_methods

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/var", response_model=VaROut)
def post_var(request: VaRRequest, db: Session = Depends(get_db)) -> VaROut:
    symbols = list(request.weights.keys())
    if len(symbols) < 2:
        raise HTTPException(
            status_code=400, detail="at least two symbols are required to estimate covariance"
        )
    weights = pd.Series(request.weights)

    try:
        results = compute_all_var_methods(
            db,
            symbols,
            weights,
            nav=request.nav,
            as_of=request.as_of,
            confidence=request.confidence,
            horizon_days=request.horizon_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    any_result = next(iter(results.values()))
    return VaROut(
        symbols=symbols,
        as_of=request.as_of,
        confidence=any_result.confidence,
        horizon_days=any_result.horizon_days,
        methods={
            name: {
                "var_pct": r.var_pct,
                "var_amount": r.var_amount,
                "es_pct": r.es_pct,
                "es_amount": r.es_amount,
            }
            for name, r in results.items()
        },
    )


@router.post("/stress/hypothetical", response_model=HypotheticalStressOut)
def post_hypothetical_stress(
    request: HypotheticalStressRequest, db: Session = Depends(get_db)
) -> HypotheticalStressOut:
    weights = pd.Series(request.weights)
    try:
        result = apply_hypothetical_scenario(db, weights, request.scenario_id, nav=request.nav)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return HypotheticalStressOut(
        scenario_id=result.scenario_id,
        pnl_pct=result.pnl_pct,
        pnl_amount=result.pnl_amount,
        instrument_shocks=result.instrument_shocks,
        unmapped_shock_keys=result.unmapped_shock_keys,
    )


@router.post("/stress/historical", response_model=HistoricalStressOut)
def post_historical_stress(
    request: HistoricalStressRequest, db: Session = Depends(get_db)
) -> HistoricalStressOut:
    weights = pd.Series(request.weights)
    try:
        result = apply_historical_scenario(db, weights, request.scenario_id, nav=request.nav)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return HistoricalStressOut(
        scenario_id=result.scenario_id,
        start_date=result.start_date,
        end_date=result.end_date,
        pnl_pct=result.pnl_pct,
        pnl_amount=result.pnl_amount,
        instrument_returns=result.instrument_returns,
        missing_symbols=result.missing_symbols,
    )


@router.get("/drawdown", response_model=DrawdownGovernorOut)
def get_drawdown_governor(
    current_drawdown: float = Query(
        ..., le=0, description="Fraction of NAV vs high-water mark, e.g. -0.06"
    ),
    risk_budget: float | None = Query(
        default=None, description="Optional risk budget to scale by the governor"
    ),
) -> DrawdownGovernorOut:
    fraction = risk_budget_fraction_for_drawdown(current_drawdown)
    governed = (
        apply_drawdown_governor(risk_budget, current_drawdown) if risk_budget is not None else None
    )
    return DrawdownGovernorOut(
        current_drawdown=current_drawdown,
        risk_budget_fraction=fraction,
        defensive_mode=is_defensive_mode(current_drawdown),
        original_risk_budget=risk_budget,
        governed_risk_budget=governed,
    )
