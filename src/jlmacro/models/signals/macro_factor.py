"""Instrument-level macro factor.

Maps a country's regime (jlmacro.models.regime, Phase 3) onto an asset-class-specific
"attractiveness of a LONG position" score, via config/signals.yaml's
`macro_score_by_regime` table - see that file's comment: qualitative fund-analyst
priors for a transparent v1, not a fitted/backtested model.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.enums import AssetClass
from jlmacro.models.instrument import Instrument
from jlmacro.models.regime import regime_status
from jlmacro.models.signals.countries import country_for_currency

# Same DE (bund) -> EA (Eurozone macro data) mapping used by valuation.py's rate
# instrument lookups.
_RATE_COUNTRY_TO_MACRO_COUNTRY: dict[str, str] = {"DE": "EA"}

# There is no "global" regime in this platform, only per-country ones; commodities
# are priced globally, so the US regime (the largest single economy this platform
# tracks) stands in as a global-growth-cycle proxy. Documented simplification, not a
# genuine global aggregate.
_COMMODITY_MACRO_COUNTRY = "US"


@dataclass
class MacroFactorResult:
    score: float | None  # 0-100; None if the relevant country/currency has no regime yet
    detail: dict[str, object] = field(default_factory=dict)


def _country_regime_score(
    session: Session, macro_country: str, asset_class_key: str
) -> tuple[float, str] | None:
    status = regime_status(session, macro_country)
    if status is None:
        return None
    table = load_yaml_config("signals")["macro_score_by_regime"][asset_class_key]
    return table.get(status.current.value, 50.0), status.current.value


def compute_macro_factor(
    session: Session, instrument: Instrument, *, as_of: dt.date
) -> MacroFactorResult:
    if instrument.asset_class == AssetClass.EQUITY_INDEX:
        if instrument.country is None:
            return MacroFactorResult(score=None)
        result = _country_regime_score(session, instrument.country, "equity_index")
        if result is None:
            return MacroFactorResult(score=None)
        score, regime = result
        return MacroFactorResult(score=score, detail={"regime": regime})

    if instrument.asset_class == AssetClass.RATE:
        if instrument.country is None:
            return MacroFactorResult(score=None)
        macro_country = _RATE_COUNTRY_TO_MACRO_COUNTRY.get(instrument.country, instrument.country)
        result = _country_regime_score(session, macro_country, "rate")
        if result is None:
            return MacroFactorResult(score=None)
        score, regime = result
        return MacroFactorResult(score=score, detail={"regime": regime})

    if instrument.asset_class == AssetClass.COMMODITY:
        result = _country_regime_score(session, _COMMODITY_MACRO_COUNTRY, "commodity")
        if result is None:
            return MacroFactorResult(score=None)
        score, regime = result
        return MacroFactorResult(score=score, detail={"regime": regime})

    if instrument.asset_class == AssetClass.FX:
        meta = instrument.metadata_json or {}
        base_ccy, quote_ccy = meta.get("base_currency"), meta.get("quote_currency")
        base_country = country_for_currency(base_ccy) if base_ccy else None
        quote_country = country_for_currency(quote_ccy) if quote_ccy else None
        if base_country is None or quote_country is None:
            return MacroFactorResult(score=None)

        base_result = _country_regime_score(session, base_country, "fx")
        quote_result = _country_regime_score(session, quote_country, "fx")
        if base_result is None or quote_result is None:
            return MacroFactorResult(score=None)

        base_score, base_regime = base_result
        quote_score, quote_regime = quote_result
        # Long-pair attractiveness is the *relative* macro backdrop of the two
        # economies, not either one's absolute level.
        score = 50.0 + (base_score - quote_score) / 2.0
        return MacroFactorResult(
            score=score, detail={"base_regime": base_regime, "quote_regime": quote_regime}
        )

    return MacroFactorResult(score=None)
