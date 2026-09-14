"""Performance fees: the standard high-water-mark model - a fee only crystallises on
NAV *above* the fund's own all-time high, never on a recovery back towards a
previous high (no "paying twice for the same gain"). `config/fees.yaml` holds the
fee rate as fund business policy, the same pattern `config/risk_limits.yaml` follows
for risk parameters.
"""

from __future__ import annotations

from dataclasses import dataclass

from jlmacro.config import load_yaml_config


@dataclass
class PerformanceFeeResult:
    nav_gross: float
    high_water_mark: float
    performance_fee_accrued: float
    nav_net: float


def fees_config() -> dict:
    return load_yaml_config("fees")


def compute_performance_fee(
    nav_gross: float, high_water_mark: float, *, performance_fee_pct: float | None = None
) -> PerformanceFeeResult:
    if performance_fee_pct is None:
        performance_fee_pct = fees_config()["performance_fee_pct"]

    gain_above_hwm = max(0.0, nav_gross - high_water_mark)
    fee = gain_above_hwm * performance_fee_pct
    return PerformanceFeeResult(
        nav_gross=nav_gross,
        high_water_mark=high_water_mark,
        performance_fee_accrued=fee,
        nav_net=nav_gross - fee,
    )
