"""Composite investment score: weighted combination of Macro, Valuation, Trend,
Positioning and Catalyst.

Weights and score-band thresholds come from config/risk_limits.yaml
(`signal_weights`, `investment_score_thresholds`) since the platform spec defines
them as fund risk policy, not signal-engine tuning.

`suggested_risk_units` is advisory only. Per the platform spec: "the risk engine has
final authority over maximum allowable position size" and "the system must never
allow score alone to override portfolio-risk limits." The risk engine itself doesn't
exist yet (Phase 5+); until it does, nothing downstream should treat this field as an
authorized position size - it is what the score alone would suggest, nothing more.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.enums import AssetClass
from jlmacro.models.instrument import Instrument
from jlmacro.models.signals.catalyst import catalyst_score
from jlmacro.models.signals.countries import country_for_currency
from jlmacro.models.signals.macro_factor import compute_macro_factor
from jlmacro.models.signals.positioning import compute_positioning
from jlmacro.models.signals.trend import compute_trend
from jlmacro.models.signals.valuation import compute_valuation

_RATE_COUNTRY_TO_MACRO_COUNTRY: dict[str, str] = {"DE": "EA"}
_COMMODITY_MACRO_COUNTRY = "US"


@dataclass
class InvestmentScore:
    instrument_symbol: str
    as_of: dt.date
    macro_score: float | None
    valuation_score: float | None
    trend_score: float | None  # rescaled to 0-100 here, from trend.py's native -100..100
    positioning_score: float | None
    catalyst_score: float | None
    composite_score: float | None  # None only if every component was unavailable
    action: str  # no_position/watchlist/half_unit/full_unit/max_unit
    suggested_risk_units: float  # 0 / 0 / 0.5 / 1 / 1.5 - advisory only, see module docstring
    detail: dict[str, object] = field(default_factory=dict)


def _primary_country_for_instrument(instrument: Instrument) -> str | None:
    """A single representative country for the catalyst engine, which (unlike
    macro_factor's FX handling) only takes one country - the base currency's economy
    stands in for an FX pair's near-term catalyst relevance.
    """
    if instrument.asset_class == AssetClass.EQUITY_INDEX:
        return instrument.country
    if instrument.asset_class == AssetClass.RATE:
        if instrument.country is None:
            return None
        return _RATE_COUNTRY_TO_MACRO_COUNTRY.get(instrument.country, instrument.country)
    if instrument.asset_class == AssetClass.COMMODITY:
        return _COMMODITY_MACRO_COUNTRY
    if instrument.asset_class == AssetClass.FX:
        base_ccy = (instrument.metadata_json or {}).get("base_currency")
        return country_for_currency(base_ccy) if base_ccy else None
    return None


def _action_and_units(score: float, thresholds: dict[str, float]) -> tuple[str, float]:
    if score < thresholds["no_position_max"]:
        return "no_position", 0.0
    if score < thresholds["watchlist_max"]:
        return "watchlist", 0.0
    if score < thresholds["half_unit_max"]:
        return "half_unit", 0.5
    if score < thresholds["full_unit_max"]:
        return "full_unit", 1.0
    return "max_unit", 1.5


def compute_investment_score(session: Session, symbol: str, *, as_of: dt.date) -> InvestmentScore:
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
    if instrument is None:
        raise ValueError(f"Unknown instrument symbol: {symbol!r}")

    weights = load_yaml_config("risk_limits")["signal_weights"]
    thresholds = load_yaml_config("risk_limits")["investment_score_thresholds"]

    macro = compute_macro_factor(session, instrument, as_of=as_of)
    valuation = compute_valuation(session, instrument, as_of=as_of)
    trend = compute_trend(session, symbol, as_of=as_of)
    positioning = compute_positioning(session, symbol, as_of=as_of)

    country = _primary_country_for_instrument(instrument)
    catalyst = catalyst_score(session, country, as_of=as_of) if country else None

    trend_score = (trend.score + 100.0) / 2.0 if trend.score is not None else None

    components: dict[str, float | None] = {
        "macro": macro.score,
        "valuation": valuation.score,
        "trend": trend_score,
        "positioning": positioning.score,
        "catalyst": catalyst.score if catalyst is not None else None,
    }
    available = {name: value for name, value in components.items() if value is not None}

    composite: float | None = None
    if available:
        total_weight = sum(weights[name] for name in available)
        composite = sum(weights[name] * value for name, value in available.items()) / total_weight

    action, suggested_units = (
        _action_and_units(composite, thresholds)
        if composite is not None
        else (
            "no_position",
            0.0,
        )
    )

    return InvestmentScore(
        instrument_symbol=instrument.symbol,
        as_of=as_of,
        macro_score=components["macro"],
        valuation_score=components["valuation"],
        trend_score=components["trend"],
        positioning_score=components["positioning"],
        catalyst_score=components["catalyst"],
        composite_score=composite,
        action=action,
        suggested_risk_units=suggested_units,
        detail={
            "trend_label": trend.label,
            "positioning_label": positioning.label,
            "valuation_method": valuation.method,
            "available_components": sorted(available.keys()),
        },
    )
