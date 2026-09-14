"""Event-driven backtester: replays the signal engine (Phase 4) and portfolio
construction (Phase 5) over history, one rebalance period at a time, always deciding
each period's weights from data knowable *before* that period starts and only then
measuring the return actually realised over it - so nothing here can look ahead.

At each rebalance date:
1. Score every candidate symbol (`compute_investment_score`, Phase 4) using only data
   as of that date.
2. Keep symbols whose action is at least `half_unit` (i.e. the composite score
   actually suggests a position) with a non-`None` composite score.
3. Build weights over the kept symbols via `jlmacro.portfolio.construction`
   (covariance from data as of that date only), signed by whether the composite
   score reads bullish (>=50) or bearish (<50), scaled to the target volatility.
4. Hold those weights unchanged until the next rebalance date, then measure the
   period's actual point-in-time return.

A period with fewer than two investable symbols (nothing scores well enough, or
there isn't yet a two-symbol covariance to build weights from) is held flat (zero
return) rather than guessing - the same "fail safe to no risk" convention used in
`jlmacro.portfolio.sizing`.

This is a v1: it doesn't yet model transaction costs, slippage, financing, or
intra-period rebalancing - see "Known limitations" in the README.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
import pandas as pd

from jlmacro.config import load_yaml_config
from jlmacro.models.signals import compute_investment_score
from jlmacro.models.signals.pit import point_in_time_closes
from jlmacro.portfolio.construction import (
    equal_risk_contribution_weights,
    inverse_volatility_weights,
    scale_to_target_volatility,
)
from jlmacro.portfolio.covariance import (
    annualised_volatility,
    ledoit_wolf_covariance,
    returns_matrix,
)

_MIN_ACTIONABLE_ACTIONS = {"half_unit", "full_unit", "max_unit"}


@dataclass
class BacktestPeriodResult:
    period_start: dt.date
    period_end: dt.date
    weights: dict[str, float]  # signed, fraction of NAV; empty if held flat
    period_return: float
    nav_start: float
    nav_end: float


@dataclass
class BacktestResult:
    start: dt.date
    end: dt.date
    nav0: float
    periods: list[BacktestPeriodResult] = field(default_factory=list)
    total_return: float = 0.0
    annualised_return: float = 0.0
    annualised_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    calmar_ratio: float = 0.0
    hit_rate: float = 0.0

    def nav_curve(self) -> pd.Series:
        dates = [self.start, *[p.period_end for p in self.periods]]
        navs = [self.nav0, *[p.nav_end for p in self.periods]]
        return pd.Series(navs, index=pd.Index(dates, name="date"))

    def period_returns(self) -> pd.Series:
        return pd.Series(
            [p.period_return for p in self.periods],
            index=pd.Index([p.period_end for p in self.periods], name="date"),
        )


def _rebalance_dates(start: dt.date, end: dt.date, frequency_days: int) -> list[dt.date]:
    dates = []
    current = start
    while current < end:
        dates.append(current)
        current = current + dt.timedelta(days=frequency_days)
    dates.append(end)
    return dates


def _realised_period_return(
    session, symbol: str, period_start: dt.date, period_end: dt.date
) -> float | None:
    window_days = (period_end - period_start).days + 10
    history = point_in_time_closes(session, symbol, as_of=period_end, window_days=window_days)
    in_window = [(d, c) for d, c in history if period_start <= d <= period_end]
    if len(in_window) < 2:
        return None
    first_close = in_window[0][1]
    last_close = in_window[-1][1]
    return (last_close / first_close) - 1.0


def _decide_weights(
    session,
    symbols: list[str],
    *,
    decision_date: dt.date,
    weighting_method: str,
    target_volatility: float | None,
) -> dict[str, float]:
    scores = {
        symbol: compute_investment_score(session, symbol, as_of=decision_date) for symbol in symbols
    }
    candidates = [
        symbol
        for symbol, score in scores.items()
        if score.action in _MIN_ACTIONABLE_ACTIONS and score.composite_score is not None
    ]
    if len(candidates) < 2:
        return {}

    returns = returns_matrix(session, candidates, as_of=decision_date)
    candidates = [s for s in candidates if s in returns.columns]
    if len(candidates) < 2:
        return {}
    returns = returns[candidates]

    covariance = ledoit_wolf_covariance(returns)
    if weighting_method == "inverse_volatility":
        raw_weights = inverse_volatility_weights(annualised_volatility(returns))
    else:
        try:
            raw_weights = equal_risk_contribution_weights(covariance)
        except RuntimeError:
            raw_weights = inverse_volatility_weights(annualised_volatility(returns))

    scaled = scale_to_target_volatility(
        raw_weights, covariance, target_volatility=target_volatility
    )

    signed_weights: dict[str, float] = {}
    for symbol in candidates:
        composite_score = scores[symbol].composite_score
        assert composite_score is not None  # guaranteed by the `candidates` filter above
        signed_weights[symbol] = float(scaled.weights[symbol]) * (
            1 if composite_score >= 50 else -1
        )
    return signed_weights


def run_backtest(
    session,
    symbols: list[str],
    *,
    start: dt.date,
    end: dt.date,
    nav0: float = 10_000_000.0,
    rebalance_frequency_days: int | None = None,
    weighting_method: str | None = None,
    target_volatility: float | None = None,
) -> BacktestResult:
    config = load_yaml_config("portfolio")
    rebalance_frequency_days = rebalance_frequency_days or 21
    weighting_method = weighting_method or config["construction"]["default_method"]

    dates = _rebalance_dates(start, end, rebalance_frequency_days)
    result = BacktestResult(start=start, end=end, nav0=nav0)
    nav = nav0

    for period_start, period_end in pairwise(dates):
        weights = _decide_weights(
            session,
            symbols,
            decision_date=period_start,
            weighting_method=weighting_method,
            target_volatility=target_volatility,
        )

        period_return = 0.0
        for symbol, weight in weights.items():
            realised = _realised_period_return(session, symbol, period_start, period_end)
            if realised is not None:
                period_return += weight * realised

        nav_start = nav
        nav = nav * (1 + period_return)
        result.periods.append(
            BacktestPeriodResult(
                period_start=period_start,
                period_end=period_end,
                weights=weights,
                period_return=period_return,
                nav_start=nav_start,
                nav_end=nav,
            )
        )

    _populate_performance_stats(result)
    return result


def _populate_performance_stats(result: BacktestResult) -> None:
    period_returns = result.period_returns()
    if period_returns.empty:
        return

    nav_curve = result.nav_curve()
    result.total_return = float(nav_curve.iloc[-1] / nav_curve.iloc[0] - 1.0)

    num_years = max((result.end - result.start).days / 365.25, 1e-9)
    result.annualised_return = float((1 + result.total_return) ** (1 / num_years) - 1)

    periods_per_year = 252.0 / max(
        1.0, (result.end - result.start).days / max(len(period_returns), 1)
    )
    result.annualised_volatility = float(period_returns.std() * np.sqrt(periods_per_year))

    if result.annualised_volatility > 0:
        result.sharpe_ratio = result.annualised_return / result.annualised_volatility

    running_max = nav_curve.cummax()
    drawdown = (nav_curve / running_max) - 1.0
    result.max_drawdown = float(drawdown.min())

    if result.max_drawdown < 0:
        result.calmar_ratio = result.annualised_return / abs(result.max_drawdown)

    result.hit_rate = float((period_returns > 0).mean())
