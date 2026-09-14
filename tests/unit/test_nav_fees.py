from __future__ import annotations

import pytest

from jlmacro.config import load_yaml_config
from jlmacro.nav.fees import compute_performance_fee, fees_config


def test_fees_config_has_starting_capital_and_performance_fee_pct():
    config = fees_config()
    assert config["starting_capital"] > 0
    assert 0 < config["performance_fee_pct"] < 1


def test_compute_performance_fee_charges_on_gain_above_high_water_mark():
    result = compute_performance_fee(1_100_000.0, 1_000_000.0, performance_fee_pct=0.20)

    assert result.performance_fee_accrued == pytest.approx(20_000.0)
    assert result.nav_net == pytest.approx(1_080_000.0)


def test_compute_performance_fee_charges_nothing_below_high_water_mark():
    result = compute_performance_fee(950_000.0, 1_000_000.0, performance_fee_pct=0.20)

    assert result.performance_fee_accrued == 0.0
    assert result.nav_net == pytest.approx(950_000.0)


def test_compute_performance_fee_charges_nothing_exactly_at_high_water_mark():
    result = compute_performance_fee(1_000_000.0, 1_000_000.0, performance_fee_pct=0.20)

    assert result.performance_fee_accrued == 0.0


def test_compute_performance_fee_uses_config_default_when_unspecified():
    expected_pct = load_yaml_config("fees")["performance_fee_pct"]
    result = compute_performance_fee(1_100_000.0, 1_000_000.0)

    assert result.performance_fee_accrued == pytest.approx(100_000.0 * expected_pct)
