from __future__ import annotations

import pytest

from jlmacro.risk.drawdown import (
    apply_drawdown_governor,
    drawdown_governor_config,
    is_defensive_mode,
    risk_budget_fraction_for_drawdown,
)


def test_no_drawdown_retains_full_risk_budget():
    assert risk_budget_fraction_for_drawdown(0.0) == 1.0
    assert risk_budget_fraction_for_drawdown(-0.01) == 1.0


def test_deepest_breached_threshold_governs():
    config = drawdown_governor_config()
    thresholds = {level["threshold"]: level["risk_budget_fraction"] for level in config["levels"]}

    assert risk_budget_fraction_for_drawdown(-0.03) == thresholds[-0.03]
    assert risk_budget_fraction_for_drawdown(-0.049) == thresholds[-0.03]
    assert risk_budget_fraction_for_drawdown(-0.05) == thresholds[-0.05]
    assert risk_budget_fraction_for_drawdown(-0.10) == thresholds[-0.10]
    assert (
        risk_budget_fraction_for_drawdown(-0.25) == thresholds[-0.10]
    )  # floors at the deepest level


def test_is_defensive_mode_triggers_at_configured_threshold():
    config = drawdown_governor_config()
    threshold = config["defensive_mode_threshold"]

    assert is_defensive_mode(threshold) is True
    assert is_defensive_mode(threshold - 0.05) is True
    assert is_defensive_mode(threshold + 0.01) is False


def test_apply_drawdown_governor_scales_risk_budget():
    config = drawdown_governor_config()
    fraction = risk_budget_fraction_for_drawdown(-0.06, config=config)

    scaled = apply_drawdown_governor(100_000.0, -0.06, config=config)

    assert scaled == pytest.approx(100_000.0 * fraction)


def test_apply_drawdown_governor_is_a_no_op_at_zero_drawdown():
    assert apply_drawdown_governor(100_000.0, 0.0) == pytest.approx(100_000.0)


@pytest.mark.parametrize("custom_drawdown", [-0.02, -0.15])
def test_custom_config_is_respected(custom_drawdown):
    custom_config = {
        "levels": [
            {"threshold": -0.01, "risk_budget_fraction": 0.8},
            {"threshold": -0.05, "risk_budget_fraction": 0.4},
        ],
        "defensive_mode_threshold": -0.05,
    }

    fraction = risk_budget_fraction_for_drawdown(custom_drawdown, config=custom_config)

    if custom_drawdown <= -0.05:
        assert fraction == 0.4
    else:
        assert fraction == 0.8
