"""Backtesting endpoints (jlmacro.backtest, Phase 7): event-driven backtest, walk-
forward validation, and Monte Carlo simulation over a backtest's realised returns.

Every backtest replays the signal engine (Phase 4) and portfolio construction
(Phase 5) exactly as they'd have run at each historical rebalance date - see
`jlmacro.backtest.engine`'s module docstring for the point-in-time discipline this
relies on. These endpoints can be slow (one investment-score computation per symbol
per rebalance date) - keep symbol lists and date ranges modest for interactive use.
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import (
    BacktestOut,
    BacktestPeriodOut,
    BacktestRequest,
    MonteCarloOut,
    MonteCarloRequest,
    WalkForwardOut,
    WalkForwardRequest,
)
from jlmacro.backtest.engine import BacktestResult, run_backtest
from jlmacro.backtest.monte_carlo import bootstrap_terminal_nav
from jlmacro.backtest.walk_forward import run_walk_forward

router = APIRouter(prefix="/backtest", tags=["backtest"])


def _to_out(result: BacktestResult) -> BacktestOut:
    return BacktestOut(
        start=result.start,
        end=result.end,
        nav0=result.nav0,
        periods=[
            BacktestPeriodOut(
                period_start=p.period_start,
                period_end=p.period_end,
                weights=p.weights,
                period_return=p.period_return,
                nav_start=p.nav_start,
                nav_end=p.nav_end,
            )
            for p in result.periods
        ],
        total_return=result.total_return,
        annualised_return=result.annualised_return,
        annualised_volatility=result.annualised_volatility,
        sharpe_ratio=result.sharpe_ratio,
        max_drawdown=result.max_drawdown,
        calmar_ratio=result.calmar_ratio,
        hit_rate=result.hit_rate,
    )


@router.post("/run", response_model=BacktestOut)
def post_backtest(request: BacktestRequest, db: Session = Depends(get_db)) -> BacktestOut:
    result = run_backtest(
        db,
        request.symbols,
        start=request.start,
        end=request.end,
        nav0=request.nav0,
        rebalance_frequency_days=request.rebalance_frequency_days,
        weighting_method=request.weighting_method,
        target_volatility=request.target_volatility,
    )
    return _to_out(result)


@router.post("/walk-forward", response_model=WalkForwardOut)
def post_walk_forward(request: WalkForwardRequest, db: Session = Depends(get_db)) -> WalkForwardOut:
    result = run_walk_forward(
        db,
        request.symbols,
        start=request.start,
        end=request.end,
        window_days=request.window_days,
        nav0=request.nav0,
        rebalance_frequency_days=request.rebalance_frequency_days,
        weighting_method=request.weighting_method,
        target_volatility=request.target_volatility,
    )
    return WalkForwardOut(
        windows=result.windows,
        results=[_to_out(r) for r in result.results],
        mean_sharpe_ratio=result.mean_sharpe_ratio,
        worst_max_drawdown=result.worst_max_drawdown,
    )


@router.post("/monte-carlo", response_model=MonteCarloOut)
def post_monte_carlo(request: MonteCarloRequest) -> MonteCarloOut:
    result = bootstrap_terminal_nav(
        pd.Series(request.period_returns),
        nav0=request.nav0,
        num_simulations=request.num_simulations,
        horizon_periods=request.horizon_periods,
        seed=request.seed,
    )
    return MonteCarloOut(
        num_simulations=result.num_simulations,
        horizon_periods=result.horizon_periods,
        nav0=result.nav0,
        terminal_nav_percentiles=result.terminal_nav_percentiles,
        probability_of_loss=result.probability_of_loss,
        max_drawdown_percentiles=result.max_drawdown_percentiles,
        probability_of_defensive_mode_breach=result.probability_of_defensive_mode_breach,
    )
