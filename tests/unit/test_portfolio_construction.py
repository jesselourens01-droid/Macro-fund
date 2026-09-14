from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from jlmacro.portfolio.construction import (
    equal_risk_contribution_weights,
    inverse_volatility_weights,
    risk_contributions,
    scale_to_target_volatility,
)

_SYMBOLS = ["A", "B", "C"]


def _covariance(vols: list[float], correlations: np.ndarray) -> pd.DataFrame:
    vol_arr = np.asarray(vols)
    cov = np.outer(vol_arr, vol_arr) * correlations
    return pd.DataFrame(cov, index=_SYMBOLS, columns=_SYMBOLS)


def test_inverse_volatility_weights_are_inversely_proportional_to_vol():
    vols = pd.Series({"A": 0.10, "B": 0.20, "C": 0.40})
    weights = inverse_volatility_weights(vols)

    assert weights.sum() == pytest.approx(1.0)
    # B should get exactly half of A's weight (vol is double); C a quarter.
    assert weights["B"] == pytest.approx(weights["A"] / 2)
    assert weights["C"] == pytest.approx(weights["A"] / 4)


def test_inverse_volatility_weights_rejects_nonpositive_vol():
    vols = pd.Series({"A": 0.10, "B": 0.0})
    with pytest.raises(ValueError, match="positive"):
        inverse_volatility_weights(vols)


def test_equal_risk_contribution_weights_equalise_risk_contributions():
    correlations = np.array(
        [
            [1.0, 0.3, 0.1],
            [0.3, 1.0, 0.2],
            [0.1, 0.2, 1.0],
        ]
    )
    cov = _covariance([0.10, 0.25, 0.40], correlations)

    weights = equal_risk_contribution_weights(cov)
    contributions = risk_contributions(weights, cov)

    assert weights.sum() == pytest.approx(1.0)
    assert (weights > 0).all()
    for symbol in _SYMBOLS:
        assert contributions[symbol] == pytest.approx(1 / 3, abs=1e-4)


def test_equal_risk_contribution_gives_lower_weight_to_higher_vol_asset():
    correlations = np.eye(3)
    cov = _covariance([0.10, 0.20, 0.40], correlations)

    weights = equal_risk_contribution_weights(cov)

    assert weights["A"] > weights["B"] > weights["C"]


def test_scale_to_target_volatility_hits_target_exactly():
    correlations = np.array(
        [
            [1.0, 0.2, 0.0],
            [0.2, 1.0, 0.1],
            [0.0, 0.1, 1.0],
        ]
    )
    cov = _covariance([0.12, 0.18, 0.30], correlations)
    weights = equal_risk_contribution_weights(cov)

    result = scale_to_target_volatility(weights, cov, target_volatility=0.09)

    w = result.weights.to_numpy()
    realised_vol = float(np.sqrt(w @ cov.to_numpy() @ w))
    assert realised_vol == pytest.approx(0.09, abs=1e-6)
    assert result.portfolio_volatility == pytest.approx(0.09)


def test_scale_to_target_volatility_uses_config_default_when_unspecified():
    from jlmacro.config import load_yaml_config

    cov = _covariance([0.15, 0.20, 0.25], np.eye(3))
    weights = inverse_volatility_weights(pd.Series({"A": 0.15, "B": 0.20, "C": 0.25}))

    result = scale_to_target_volatility(weights, cov)

    expected_target = load_yaml_config("risk_limits")["target_volatility"]
    assert result.portfolio_volatility == pytest.approx(expected_target)
