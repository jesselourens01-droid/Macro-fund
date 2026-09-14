"""Monte Carlo simulation over a backtest's realised period returns.

Answers a question a single equity curve can't: given the *distribution* of returns
this strategy actually produced, what does the range of plausible future outcomes
look like - not just the one path that happened to occur? Implemented as a
bootstrap (resampling the historical period returns with replacement) rather than a
parametric distribution, so it makes no assumption about the shape of the return
distribution beyond "the future resembles this sample" - the same honest limitation
every bootstrap has, worth remembering for a short backtest history.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from jlmacro.risk.drawdown import drawdown_governor_config


@dataclass
class MonteCarloResult:
    num_simulations: int
    horizon_periods: int
    nav0: float
    terminal_nav_percentiles: dict[str, float]
    probability_of_loss: float
    max_drawdown_percentiles: dict[str, float]
    probability_of_defensive_mode_breach: float


_PERCENTILES = {"p5": 5, "p25": 25, "p50": 50, "p75": 75, "p95": 95}


def bootstrap_terminal_nav(
    period_returns: pd.Series,
    *,
    nav0: float,
    num_simulations: int = 10_000,
    horizon_periods: int | None = None,
    seed: int | None = None,
) -> MonteCarloResult:
    if len(period_returns) == 0:
        raise ValueError("period_returns must not be empty")

    horizon_periods = horizon_periods if horizon_periods is not None else len(period_returns)
    rng = np.random.default_rng(seed)

    sampled_returns = rng.choice(
        period_returns.to_numpy(), size=(num_simulations, horizon_periods), replace=True
    )
    growth_factors = 1 + sampled_returns
    cumulative_paths = nav0 * np.cumprod(growth_factors, axis=1)

    terminal_nav = cumulative_paths[:, -1]
    running_max = np.maximum.accumulate(cumulative_paths, axis=1)
    drawdown_paths = (cumulative_paths / running_max) - 1.0
    max_drawdown_per_path = drawdown_paths.min(axis=1)

    defensive_threshold = drawdown_governor_config()["defensive_mode_threshold"]
    probability_of_defensive_mode_breach = float(
        (max_drawdown_per_path <= defensive_threshold).mean()
    )

    return MonteCarloResult(
        num_simulations=num_simulations,
        horizon_periods=horizon_periods,
        nav0=nav0,
        terminal_nav_percentiles={
            label: float(np.percentile(terminal_nav, pct)) for label, pct in _PERCENTILES.items()
        },
        probability_of_loss=float((terminal_nav < nav0).mean()),
        max_drawdown_percentiles={
            label: float(np.percentile(max_drawdown_per_path, pct))
            for label, pct in _PERCENTILES.items()
        },
        probability_of_defensive_mode_breach=probability_of_defensive_mode_breach,
    )
