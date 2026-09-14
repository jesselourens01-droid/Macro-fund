"""Risk-based position sizing.

Per the platform spec: `risk_budget = NAV x allowed_risk_percentage`,
`position_size = risk_budget / expected_loss_percentage`. `allowed_risk_percentage`
comes from the risk unit a trade earned via the Phase 4 composite investment score
(0 / 0 / 0.5 / 1 / 1.5, mapped here onto config/risk_limits.yaml's existing
`position_risk` percentages - normal_min/normal_max/high_conviction_max - rather than
introducing a second, competing set of numbers). `expected_loss_percentage` is the
ATR-based stop distance already computed by the trend engine (jlmacro.models.signals.trend),
expressed as a fraction of price.

This module answers "how big should this position be," never "should this position
exist at all" - score-band gating (no_position/watchlist/...) happens in
jlmacro.models.signals.composite, and portfolio-level caps (max gross/net exposure,
concentration limits) happen in jlmacro.portfolio.construction /
jlmacro.portfolio.exposures. Per the spec, none of these layers may be skipped in
favour of "the score said so."
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.signals.pit import point_in_time_closes
from jlmacro.models.signals.trend import compute_trend

# Risk units (from the Phase 4 composite score's action band) -> which
# config/risk_limits.yaml `position_risk` percentage applies. 0.0 (no_position/
# watchlist) intentionally has no entry - sizing a position with zero conviction
# isn't a "very small size," it's "don't size this at all."
_RISK_UNIT_TO_CONFIG_KEY: dict[float, str] = {
    0.5: "normal_min",
    1.0: "normal_max",
    1.5: "high_conviction_max",
}


@dataclass
class PositionSizeResult:
    symbol: str
    direction: int  # +1 long, -1 short
    risk_units: float
    risk_pct_nav: float  # fraction of NAV this position is allowed to lose before its stop
    stop_distance_pct: float | None  # ATR / price; None if not computable
    risk_budget: float  # NAV * risk_pct_nav, in NAV's currency
    notional: (
        float | None
    )  # risk_budget / stop_distance_pct; None if stop_distance_pct is None/zero
    price: float | None


def risk_pct_for_units(risk_units: float) -> float:
    """0.0 for any risk_units not in {0.5, 1.0, 1.5} (i.e. no_position/watchlist, or
    an unrecognised value) - deliberately fails safe to "no risk budget" rather than
    guessing.
    """
    config_key = _RISK_UNIT_TO_CONFIG_KEY.get(risk_units)
    if config_key is None:
        return 0.0
    return load_yaml_config("risk_limits")["position_risk"][config_key]


def compute_position_size(
    session: Session,
    symbol: str,
    *,
    nav: float,
    risk_units: float,
    direction: int,
    as_of: dt.date,
) -> PositionSizeResult:
    risk_pct_nav = risk_pct_for_units(risk_units)
    risk_budget = nav * risk_pct_nav

    trend = compute_trend(session, symbol, as_of=as_of)
    closes = point_in_time_closes(session, symbol, as_of=as_of, window_days=10)
    price = closes[-1][1] if closes else None

    stop_distance_pct: float | None = None
    if trend.atr is not None and price is not None and price > 0:
        stop_distance_pct = trend.atr / price

    notional: float | None = None
    if stop_distance_pct is not None and stop_distance_pct > 0 and risk_budget > 0:
        notional = risk_budget / stop_distance_pct

    return PositionSizeResult(
        symbol=symbol,
        direction=direction,
        risk_units=risk_units,
        risk_pct_nav=risk_pct_nav,
        stop_distance_pct=stop_distance_pct,
        risk_budget=risk_budget,
        notional=notional,
        price=price,
    )
