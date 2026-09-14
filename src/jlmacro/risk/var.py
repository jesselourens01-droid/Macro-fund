"""Value-at-Risk and Expected Shortfall, three ways.

All three answer the same question - "how much could this portfolio lose over the
next N days, at a given confidence level" - from different assumptions:

- `historical_var`: the empirical distribution of what *actually* happened, replaying
  today's weights against real point-in-time daily returns. Makes no distributional
  assumption, but is only as good as the history available and assumes today's
  correlations resemble the sample's.
- `parametric_var`: assumes daily portfolio returns are Gaussian with the given
  volatility. Fast, analytic, but understates tail risk for genuinely fat-tailed
  markets - which is exactly why it's never the only number reported.
- `monte_carlo_var`: simulates many correlated Gaussian return paths from the
  covariance matrix. Same distributional assumption as parametric (this
  implementation doesn't yet draw from a fatter-tailed distribution), but captures
  the portfolio's actual cross-asset correlation structure rather than reducing it to
  one scalar volatility number, and extends naturally to non-linear scenarios later.

Every horizon scaling here uses the standard sqrt(time) rule, which assumes
identically- and independently-distributed daily returns - a simplification the
platform spec doesn't ask us to relax, and one worth remembering when volatility is
clearly clustering (e.g. immediately after a shock).

VaR/ES are reported as *positive* fractions/amounts of NAV representing a loss, per
convention (a "1-day 99% VaR of 2%" means a 1% chance of losing more than 2% of NAV
over one day) - never signed P&L.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from jlmacro.config import load_yaml_config
from jlmacro.portfolio.covariance import ledoit_wolf_covariance, returns_matrix


@dataclass
class VaRResult:
    method: str
    confidence: float
    horizon_days: int
    var_pct: float  # fraction of NAV, positive = loss
    var_amount: float
    es_pct: float  # Expected Shortfall - mean loss in the tail beyond VaR
    es_amount: float


def var_config() -> dict:
    return load_yaml_config("risk_limits")["var"]


def portfolio_returns_series(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Daily portfolio return series: today's weights applied to each historical
    day's instrument returns (not each day's own weights, which we have no record of
    - this is "what would today's portfolio have earned on that day," the standard
    historical-VaR convention).
    """
    aligned_weights = weights.reindex(returns.columns).fillna(0.0)
    return returns.dot(aligned_weights)


def historical_var(
    returns: pd.DataFrame, weights: pd.Series, *, nav: float, confidence: float, horizon_days: int
) -> VaRResult:
    daily_pnl = portfolio_returns_series(returns, weights)
    if len(daily_pnl) < 2:
        raise ValueError("not enough historical returns to estimate historical VaR")

    horizon_pnl = daily_pnl * np.sqrt(horizon_days)
    loss = -horizon_pnl
    var_pct = float(np.quantile(loss, confidence))
    tail = loss[loss >= var_pct]
    es_pct = float(tail.mean()) if len(tail) > 0 else var_pct

    return VaRResult(
        method="historical",
        confidence=confidence,
        horizon_days=horizon_days,
        var_pct=var_pct,
        var_amount=var_pct * nav,
        es_pct=es_pct,
        es_amount=es_pct * nav,
    )


def parametric_var(
    daily_volatility: float, *, nav: float, confidence: float, horizon_days: int
) -> VaRResult:
    """Delta-normal VaR/ES from a single portfolio-level daily volatility (e.g. from
    `jlmacro.portfolio.construction.scale_to_target_volatility`'s realised vol,
    de-annualised) - assumes zero mean daily return, standard for short horizons.
    """
    if daily_volatility <= 0:
        raise ValueError("daily_volatility must be positive")

    z = float(norm.ppf(confidence))
    horizon_vol = daily_volatility * np.sqrt(horizon_days)
    var_pct = z * horizon_vol
    # Analytic Gaussian tail expectation: E[loss | loss > VaR] = vol * phi(z) / (1 - confidence).
    es_pct = horizon_vol * float(norm.pdf(z)) / (1 - confidence)

    return VaRResult(
        method="parametric",
        confidence=confidence,
        horizon_days=horizon_days,
        var_pct=var_pct,
        var_amount=var_pct * nav,
        es_pct=es_pct,
        es_amount=es_pct * nav,
    )


def monte_carlo_var(
    covariance: pd.DataFrame,
    weights: pd.Series,
    *,
    nav: float,
    confidence: float,
    horizon_days: int,
    num_simulations: int = 20_000,
    seed: int | None = None,
) -> VaRResult:
    """Simulates `num_simulations` correlated Gaussian daily-return draws from the
    (annualised) covariance matrix, scaled to the horizon, and applies today's
    weights to each - capturing actual cross-asset correlation rather than
    collapsing it into one volatility scalar the way `parametric_var` does.
    """
    aligned_weights = weights.reindex(covariance.columns).fillna(0.0).to_numpy()
    daily_cov = covariance.to_numpy() / 252.0
    horizon_cov = daily_cov * horizon_days

    rng = np.random.default_rng(seed)
    simulated_returns = rng.multivariate_normal(
        mean=np.zeros(len(aligned_weights)), cov=horizon_cov, size=num_simulations
    )
    simulated_pnl = simulated_returns @ aligned_weights
    loss = -simulated_pnl

    var_pct = float(np.quantile(loss, confidence))
    tail = loss[loss >= var_pct]
    es_pct = float(tail.mean()) if len(tail) > 0 else var_pct

    return VaRResult(
        method="monte_carlo",
        confidence=confidence,
        horizon_days=horizon_days,
        var_pct=var_pct,
        var_amount=var_pct * nav,
        es_pct=es_pct,
        es_amount=es_pct * nav,
    )


def compute_all_var_methods(
    session,
    symbols: list[str],
    weights: pd.Series,
    *,
    nav: float,
    as_of: dt.date,
    confidence: float | None = None,
    horizon_days: int | None = None,
) -> dict[str, VaRResult]:
    """Convenience wrapper: one point-in-time covariance/returns estimate, all three
    VaR methods computed from it, so a caller (API/dashboard) doesn't have to
    duplicate the covariance plumbing three times.
    """
    config = var_config()
    confidence = confidence if confidence is not None else config["confidence"]
    horizon_days = horizon_days if horizon_days is not None else config["horizons_days"][0]

    returns = returns_matrix(session, symbols, as_of=as_of)
    missing = [s for s in symbols if s not in returns.columns]
    if missing:
        raise ValueError(f"no point-in-time price history for symbols: {missing}")

    covariance = ledoit_wolf_covariance(returns)
    daily_vol = float(np.sqrt(portfolio_returns_series(returns, weights).var()))

    return {
        "historical": historical_var(
            returns, weights, nav=nav, confidence=confidence, horizon_days=horizon_days
        ),
        "parametric": parametric_var(
            daily_vol, nav=nav, confidence=confidence, horizon_days=horizon_days
        ),
        "monte_carlo": monte_carlo_var(
            covariance, weights, nav=nav, confidence=confidence, horizon_days=horizon_days
        ),
    }
