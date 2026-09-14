from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from jlmacro.risk.var import (
    historical_var,
    monte_carlo_var,
    parametric_var,
    portfolio_returns_series,
)


def test_portfolio_returns_series_applies_current_weights_to_each_historical_day():
    returns = pd.DataFrame({"A": [0.01, -0.02, 0.03], "B": [0.02, 0.01, -0.01]}, index=[0, 1, 2])
    weights = pd.Series({"A": 0.5, "B": 0.5})

    pnl = portfolio_returns_series(returns, weights)

    assert pnl.iloc[0] == pytest.approx(0.015)
    assert pnl.iloc[1] == pytest.approx(-0.005)
    assert pnl.iloc[2] == pytest.approx(0.01)


def test_historical_var_reports_positive_loss_fraction_and_es_at_least_var():
    rng = np.random.default_rng(7)
    returns = pd.DataFrame({"A": rng.normal(0, 0.01, 500), "B": rng.normal(0, 0.02, 500)})
    weights = pd.Series({"A": 0.6, "B": 0.4})

    result = historical_var(returns, weights, nav=1_000_000.0, confidence=0.99, horizon_days=1)

    assert result.method == "historical"
    assert result.var_pct > 0
    assert result.es_pct >= result.var_pct
    assert result.var_amount == pytest.approx(result.var_pct * 1_000_000.0)


def test_historical_var_requires_enough_observations():
    returns = pd.DataFrame({"A": [0.01]})
    weights = pd.Series({"A": 1.0})
    with pytest.raises(ValueError, match="not enough"):
        historical_var(returns, weights, nav=1_000_000.0, confidence=0.99, horizon_days=1)


def test_parametric_var_scales_with_sqrt_horizon_and_confidence():
    base = parametric_var(0.01, nav=1_000_000.0, confidence=0.99, horizon_days=1)
    five_day = parametric_var(0.01, nav=1_000_000.0, confidence=0.99, horizon_days=5)
    higher_confidence = parametric_var(0.01, nav=1_000_000.0, confidence=0.999, horizon_days=1)

    assert five_day.var_pct == pytest.approx(base.var_pct * (5**0.5))
    assert higher_confidence.var_pct > base.var_pct
    assert base.es_pct > base.var_pct  # Gaussian ES is always strictly above VaR


def test_parametric_var_rejects_nonpositive_volatility():
    with pytest.raises(ValueError, match="positive"):
        parametric_var(0.0, nav=1_000_000.0, confidence=0.99, horizon_days=1)


def test_monte_carlo_var_is_in_the_same_ballpark_as_parametric_for_gaussian_returns():
    symbols = ["A", "B"]
    cov = pd.DataFrame([[0.04, 0.0], [0.0, 0.09]], index=symbols, columns=symbols)  # annualised
    weights = pd.Series({"A": 0.5, "B": 0.5})

    mc = monte_carlo_var(
        cov,
        weights,
        nav=1_000_000.0,
        confidence=0.99,
        horizon_days=1,
        num_simulations=50_000,
        seed=1,
    )
    portfolio_daily_var = float((weights.to_numpy() @ cov.to_numpy() @ weights.to_numpy()) / 252.0)
    daily_vol = portfolio_daily_var**0.5
    param = parametric_var(daily_vol, nav=1_000_000.0, confidence=0.99, horizon_days=1)

    assert mc.var_pct == pytest.approx(param.var_pct, rel=0.1)


def test_monte_carlo_var_is_deterministic_given_a_seed():
    cov = pd.DataFrame([[0.04, 0.01], [0.01, 0.09]], index=["A", "B"], columns=["A", "B"])
    weights = pd.Series({"A": 0.6, "B": 0.4})

    first = monte_carlo_var(cov, weights, nav=1_000_000.0, confidence=0.99, horizon_days=1, seed=99)
    second = monte_carlo_var(
        cov, weights, nav=1_000_000.0, confidence=0.99, horizon_days=1, seed=99
    )

    assert first.var_pct == second.var_pct
    assert first.es_pct == second.es_pct
