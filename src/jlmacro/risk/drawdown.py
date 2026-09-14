"""The drawdown governor: config/risk_limits.yaml's `drawdown_governor` schedule,
turned into an actual multiplier on the risk budget Phase 5's sizing functions would
otherwise use.

`current_drawdown` is always a fraction of NAV relative to the fund's high-water mark,
zero or negative (e.g. -0.06 for a 6% drawdown) - this module doesn't compute it from
NAV history (there's no persisted NAV series until Phase 9's NAV engine), it only maps
a given drawdown onto the configured response. Callers pass whatever drawdown figure
they have; Phase 9 will supply a real one.
"""

from __future__ import annotations

from jlmacro.config import load_yaml_config


def drawdown_governor_config() -> dict:
    return load_yaml_config("risk_limits")["drawdown_governor"]


def risk_budget_fraction_for_drawdown(
    current_drawdown: float, *, config: dict | None = None
) -> float:
    """Fraction of the normal risk budget retained at the given drawdown level.
    Levels are keyed by threshold (negative, e.g. -0.05) -> fraction retained; the
    deepest breached threshold (most negative one satisfied) wins, since that's the
    most restrictive applicable rule. No breach at all -> full risk budget (1.0).
    """
    config = config if config is not None else drawdown_governor_config()
    for level in sorted(config["levels"], key=lambda lvl: lvl["threshold"]):
        if current_drawdown <= level["threshold"]:
            return float(level["risk_budget_fraction"])
    return 1.0


def is_defensive_mode(current_drawdown: float, *, config: dict | None = None) -> bool:
    """True once the drawdown has breached `defensive_mode_threshold` - the platform
    spec's trigger for a qualitatively different posture (e.g. no new max-conviction
    positions), not just a smaller number.
    """
    config = config if config is not None else drawdown_governor_config()
    return current_drawdown <= config["defensive_mode_threshold"]


def apply_drawdown_governor(
    risk_budget: float, current_drawdown: float, *, config: dict | None = None
) -> float:
    """Scales a risk budget (e.g. `jlmacro.portfolio.sizing.PositionSizeResult.risk_budget`)
    by the current drawdown level's retained fraction - the governor's actual point of
    enforcement.
    """
    return risk_budget * risk_budget_fraction_for_drawdown(current_drawdown, config=config)
