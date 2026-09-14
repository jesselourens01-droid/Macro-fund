from __future__ import annotations

import pandas as pd
import pytest

from jlmacro.backtest.monte_carlo import bootstrap_terminal_nav


def test_bootstrap_terminal_nav_rejects_empty_returns():
    with pytest.raises(ValueError, match="not be empty"):
        bootstrap_terminal_nav(pd.Series([], dtype=float), nav0=1_000_000.0)


def test_bootstrap_terminal_nav_percentiles_are_ordered():
    returns = pd.Series([0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.005])
    result = bootstrap_terminal_nav(returns, nav0=1_000_000.0, num_simulations=5_000, seed=1)

    p = result.terminal_nav_percentiles
    assert p["p5"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p95"]

    dd = result.max_drawdown_percentiles
    assert dd["p5"] <= dd["p25"] <= dd["p50"] <= dd["p75"] <= dd["p95"] <= 0.0

    assert 0.0 <= result.probability_of_loss <= 1.0
    assert 0.0 <= result.probability_of_defensive_mode_breach <= 1.0


def test_bootstrap_terminal_nav_all_positive_returns_never_shows_a_loss():
    returns = pd.Series([0.01, 0.02, 0.015, 0.03])
    result = bootstrap_terminal_nav(returns, nav0=1_000_000.0, num_simulations=2_000, seed=7)

    assert result.probability_of_loss == 0.0
    assert result.terminal_nav_percentiles["p5"] >= 1_000_000.0


def test_bootstrap_terminal_nav_is_deterministic_given_a_seed():
    returns = pd.Series([0.01, -0.02, 0.015, -0.005])

    first = bootstrap_terminal_nav(returns, nav0=1_000_000.0, num_simulations=1_000, seed=42)
    second = bootstrap_terminal_nav(returns, nav0=1_000_000.0, num_simulations=1_000, seed=42)

    assert first.terminal_nav_percentiles == second.terminal_nav_percentiles


def test_bootstrap_terminal_nav_respects_custom_horizon():
    returns = pd.Series([0.01, -0.02, 0.015, -0.005, 0.02])
    result = bootstrap_terminal_nav(
        returns, nav0=1_000_000.0, num_simulations=1_000, horizon_periods=50, seed=3
    )

    assert result.horizon_periods == 50
