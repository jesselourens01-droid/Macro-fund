"""Portfolio-level weighting: turn a covariance matrix (jlmacro.portfolio.covariance)
into a set of weights, then scale that weight set to the fund's target volatility
(config/risk_limits.yaml's `target_volatility`).

Two methods, matching the platform spec:
- `inverse_volatility_weights`: weight inversely proportional to each instrument's own
  volatility, ignoring correlation entirely. Simple, always well-defined, the fallback.
- `equal_risk_contribution_weights`: each position contributes equally to total
  portfolio variance, accounting for correlation. The spec's more sophisticated
  default. Solved via Spinu's convex formulation (minimize 0.5 w'Σw - sum(log(w)),
  w >= 0, then renormalise to sum to 1) rather than a heuristic iterative scheme,
  so the result is a verifiable global optimum rather than "whatever the iteration
  happened to converge to."

Neither function decides *whether* to hold a position (that's the composite score's
job) or enforces portfolio-level caps (that's jlmacro.portfolio.exposures /
jlmacro.risk) - they only turn "these symbols, this covariance" into relative weights.
"""

from __future__ import annotations

from dataclasses import dataclass

import cvxpy as cp
import numpy as np
import pandas as pd

from jlmacro.config import load_yaml_config


@dataclass
class PortfolioWeights:
    weights: pd.Series  # symbol -> weight, sums to `gross_leverage`
    gross_leverage: float  # sum of |weights|; the scaling factor applied to hit target vol
    portfolio_volatility: float  # annualised, post-scaling


def inverse_volatility_weights(volatility: pd.Series) -> pd.Series:
    """Weight each symbol 1/vol, normalised to sum to 1. Ignores correlation - two
    highly-correlated instruments both get sized as if they were independent, which is
    exactly why this is the fallback rather than the default.
    """
    if (volatility <= 0).any():
        raise ValueError("volatility must be strictly positive for every symbol")
    inverse = 1.0 / volatility
    return inverse / inverse.sum()


def equal_risk_contribution_weights(
    covariance: pd.DataFrame, *, max_iterations: int | None = None, tolerance: float | None = None
) -> pd.Series:
    """Weights such that each symbol's contribution to total portfolio variance
    (`w_i * (Σw)_i`) is equal, via Spinu's convex log-barrier formulation. Falls back
    to inverse-volatility weights (with a note in the caller's caveat, not silently)
    only if the solver fails to converge - it should not, for a well-conditioned
    (e.g. Ledoit-Wolf shrunk) covariance matrix.
    """
    config = load_yaml_config("portfolio")["construction"]
    max_iterations = max_iterations if max_iterations is not None else config["max_iterations"]
    tolerance = tolerance if tolerance is not None else config["convergence_tolerance"]

    symbols = list(covariance.columns)
    n = len(symbols)
    sigma = covariance.to_numpy()

    w = cp.Variable(n, pos=True)
    risk_term = 0.5 * cp.quad_form(w, cp.psd_wrap(sigma))
    log_barrier = cp.sum(cp.log(w)) / n
    problem = cp.Problem(cp.Minimize(risk_term - log_barrier))
    optimal_value = problem.solve(
        solver=cp.CLARABEL, max_iter=max_iterations, tol_gap_abs=tolerance
    )
    if w.value is None or optimal_value is None or not np.isfinite(optimal_value):
        raise RuntimeError(
            "equal-risk-contribution solver failed to converge; "
            "fall back to inverse_volatility_weights"
        )

    raw = np.asarray(w.value).clip(min=0.0)
    return pd.Series(raw / raw.sum(), index=symbols)


def risk_contributions(weights: pd.Series, covariance: pd.DataFrame) -> pd.Series:
    """Each symbol's share of total portfolio variance: `w_i * (Σw)_i / (w'Σw)`. Sums
    to 1 across symbols. Used to verify an ERC solution (all entries should be ~1/n)
    and, unmodified, doubles as a diagnostic for inverse-vol or any other weight set.
    """
    w = weights.reindex(covariance.columns).to_numpy()
    sigma = covariance.to_numpy()
    marginal = sigma @ w
    portfolio_variance = float(w @ marginal)
    if portfolio_variance <= 0:
        raise ValueError("portfolio variance must be positive")
    return pd.Series((w * marginal) / portfolio_variance, index=covariance.columns)


def scale_to_target_volatility(
    weights: pd.Series, covariance: pd.DataFrame, *, target_volatility: float | None = None
) -> PortfolioWeights:
    """Scale a normalised (sum-to-1) weight set up or down so the resulting
    portfolio's annualised volatility equals the fund's target (config/risk_limits.yaml
    `target_volatility`), i.e. leverage the "shape" of the portfolio to the right
    overall risk level rather than changing the relative sizing between positions.
    """
    if target_volatility is None:
        target_volatility = load_yaml_config("risk_limits")["target_volatility"]

    aligned = weights.reindex(covariance.columns)
    w = aligned.to_numpy()
    sigma = covariance.to_numpy()
    unscaled_volatility = float(np.sqrt(w @ sigma @ w))
    if unscaled_volatility <= 0:
        raise ValueError("unscaled portfolio volatility must be positive")

    gross_leverage = target_volatility / unscaled_volatility
    scaled = aligned * gross_leverage
    return PortfolioWeights(
        weights=scaled,
        gross_leverage=float(gross_leverage),
        portfolio_volatility=float(target_volatility),
    )
