"""Portfolio construction endpoints (jlmacro.portfolio, Phase 5): point-in-time
covariance estimation, weighting (inverse-vol / equal-risk-contribution) scaled to the
fund's target volatility, risk-based position sizing, and exposure/risk decomposition.

These endpoints compute and return numbers; they do not persist positions (there is no
Position/Trade table yet - that's Phase 8) and they do not enforce
config/risk_limits.yaml's limits (that's the Phase 6 risk engine's job). A weight or
size coming back from here is a proposal, not an executed or even approved trade.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import (
    CovarianceOut,
    ExposureOut,
    ExposureRequest,
    PortfolioWeightsOut,
    PositionSizeOut,
)
from jlmacro.config import load_yaml_config
from jlmacro.portfolio.construction import (
    equal_risk_contribution_weights,
    inverse_volatility_weights,
    risk_contributions,
    scale_to_target_volatility,
)
from jlmacro.portfolio.covariance import (
    annualised_volatility,
    ewma_covariance,
    ledoit_wolf_covariance,
    returns_matrix,
    sample_covariance,
)
from jlmacro.portfolio.exposures import (
    component_contribution_to_risk,
    compute_exposures,
    marginal_contribution_to_risk,
)
from jlmacro.portfolio.sizing import compute_position_size

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

_COVARIANCE_METHODS = {
    "sample": sample_covariance,
    "ewma": ewma_covariance,
    "ledoit_wolf": ledoit_wolf_covariance,
}


def _parse_symbols(symbols: str) -> list[str]:
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if len(parsed) < 2:
        raise HTTPException(
            status_code=400, detail="at least two symbols are required to estimate covariance"
        )
    return parsed


def _compute_covariance(db: Session, symbols: list[str], *, as_of: dt.date, method: str):
    estimator = _COVARIANCE_METHODS.get(method)
    if estimator is None:
        raise HTTPException(
            status_code=400,
            detail=f"unknown covariance method '{method}'; choose one of {sorted(_COVARIANCE_METHODS)}",
        )
    returns = returns_matrix(db, symbols, as_of=as_of)
    missing = [s for s in symbols if s not in returns.columns]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"no point-in-time price history for symbols: {missing}"
        )
    return returns, estimator(returns)


@router.get("/covariance", response_model=CovarianceOut)
def get_covariance(
    symbols: str = Query(..., description="Comma-separated instrument symbols, e.g. SPX,US10Y,XAU"),
    as_of: dt.date | None = Query(
        default=None, description="Point-in-time cutoff; defaults to today"
    ),
    method: str = Query(default="ledoit_wolf", description="sample | ewma | ledoit_wolf"),
    db: Session = Depends(get_db),
) -> CovarianceOut:
    as_of = as_of or dt.datetime.now(dt.UTC).date()
    parsed_symbols = _parse_symbols(symbols)
    returns, cov = _compute_covariance(db, parsed_symbols, as_of=as_of, method=method)
    vol = annualised_volatility(returns)

    return CovarianceOut(
        symbols=list(cov.columns),
        as_of=as_of,
        method=method,
        annualised_volatility=vol.to_dict(),
        covariance={row: cov.loc[row].to_dict() for row in cov.index},
    )


@router.get("/weights", response_model=PortfolioWeightsOut)
def get_weights(
    symbols: str = Query(..., description="Comma-separated instrument symbols, e.g. SPX,US10Y,XAU"),
    as_of: dt.date | None = Query(
        default=None, description="Point-in-time cutoff; defaults to today"
    ),
    covariance_method: str = Query(
        default="ledoit_wolf", description="sample | ewma | ledoit_wolf"
    ),
    weighting_method: str | None = Query(
        default=None,
        description="inverse_volatility | equal_risk_contribution (defaults to config)",
    ),
    target_volatility: float | None = Query(
        default=None, description="Annualised target vol; defaults to config/risk_limits.yaml"
    ),
    db: Session = Depends(get_db),
) -> PortfolioWeightsOut:
    as_of = as_of or dt.datetime.now(dt.UTC).date()
    parsed_symbols = _parse_symbols(symbols)
    weighting_method = (
        weighting_method or load_yaml_config("portfolio")["construction"]["default_method"]
    )

    returns, cov = _compute_covariance(db, parsed_symbols, as_of=as_of, method=covariance_method)
    vol = annualised_volatility(returns)

    if weighting_method == "inverse_volatility":
        raw_weights = inverse_volatility_weights(vol)
    elif weighting_method == "equal_risk_contribution":
        try:
            raw_weights = equal_risk_contribution_weights(cov)
        except RuntimeError:
            raw_weights = inverse_volatility_weights(vol)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"unknown weighting method '{weighting_method}'; choose inverse_volatility or equal_risk_contribution",
        )

    scaled = scale_to_target_volatility(raw_weights, cov, target_volatility=target_volatility)
    contributions = risk_contributions(raw_weights, cov)

    return PortfolioWeightsOut(
        symbols=list(cov.columns),
        as_of=as_of,
        method=weighting_method,
        target_volatility=scaled.portfolio_volatility,
        gross_leverage=scaled.gross_leverage,
        portfolio_volatility=scaled.portfolio_volatility,
        weights=scaled.weights.to_dict(),
        risk_contributions=contributions.to_dict(),
    )


@router.get("/sizing/{symbol}", response_model=PositionSizeOut)
def get_position_size(
    symbol: str,
    nav: float = Query(..., gt=0, description="Fund NAV in its base currency"),
    risk_units: float = Query(
        ..., description="0.5 / 1.0 / 1.5, from the Phase 4 composite score's action band"
    ),
    direction: int = Query(..., description="+1 long, -1 short"),
    as_of: dt.date | None = Query(
        default=None, description="Point-in-time cutoff; defaults to today"
    ),
    db: Session = Depends(get_db),
) -> PositionSizeOut:
    as_of = as_of or dt.datetime.now(dt.UTC).date()
    result = compute_position_size(
        db, symbol.upper(), nav=nav, risk_units=risk_units, direction=direction, as_of=as_of
    )
    return PositionSizeOut(
        symbol=result.symbol,
        as_of=as_of,
        direction=result.direction,
        risk_units=result.risk_units,
        risk_pct_nav=result.risk_pct_nav,
        stop_distance_pct=result.stop_distance_pct,
        risk_budget=result.risk_budget,
        notional=result.notional,
        price=result.price,
    )


@router.post("/exposures", response_model=ExposureOut)
def post_exposures(request: ExposureRequest, db: Session = Depends(get_db)) -> ExposureOut:
    """Takes an explicit set of signed weights (not read from any persisted
    position table, since none exists yet) and returns exposure breakdowns plus
    marginal/component contribution to risk, computed against a covariance matrix
    estimated as of `as_of` for exactly those symbols.
    """
    symbols = list(request.weights.keys())
    if len(symbols) < 2:
        raise HTTPException(
            status_code=400, detail="at least two symbols are required to estimate covariance"
        )
    weights = pd.Series(request.weights)

    _, cov = _compute_covariance(db, symbols, as_of=request.as_of, method=request.covariance_method)
    summary = compute_exposures(db, weights)
    mcr = marginal_contribution_to_risk(weights, cov)
    ccr = component_contribution_to_risk(weights, cov)

    return ExposureOut(
        gross=summary.gross,
        net=summary.net,
        by_asset_class=summary.by_asset_class,
        by_country=summary.by_country,
        by_currency=summary.by_currency,
        marginal_contribution_to_risk=mcr.to_dict(),
        component_contribution_to_risk=ccr.to_dict(),
        portfolio_volatility=float(ccr.sum()),
    )
