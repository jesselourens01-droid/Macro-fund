"""Asset-class-specific valuation engine.

Real, first-principles calculations where we have the data for them (FX real-rate
differential, RATE real yield); honestly-documented proxies elsewhere, because this
platform does not yet have real earnings, futures-curve, or inventory data sources
(those are Phase 2+ work - see config/signals.yaml's top comment):

- EQUITY_INDEX: a mean-reversion-vs-own-trend proxy (rich/cheap relative to the
  instrument's OWN price history, not a true fundamental fair value from earnings).
- COMMODITY: a US-real-rate-sensitivity proxy (non-yielding assets tend to look
  "cheap" when real rates are low/falling), not a real futures-curve/inventory model.

Every ValuationResult reports which `method` produced it, so nothing here pretends to
be more rigorous than it is. All scores are 0-100, framed consistently with the rest
of the signal engines as "attractiveness of a LONG position" (50 = neutral).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.enums import AssetClass
from jlmacro.models.instrument import Instrument
from jlmacro.models.regime.scoring import point_in_time_history
from jlmacro.models.signals.countries import country_for_currency
from jlmacro.models.signals.pit import point_in_time_closes

# Eurozone rate instruments (the German bund, DE10Y) are quoted under country="DE" in
# the instrument universe, while Eurozone-wide macro data (CPI etc.) is tracked under
# the code "EA" - this maps a macro country back to the country its benchmark rate
# instrument is actually filed under.
_RATE_INSTRUMENT_COUNTRY_OVERRIDE: dict[str, str] = {"EA": "DE"}
_BENCHMARK_TENOR_YEARS = 10


@dataclass
class ValuationResult:
    score: float | None  # 0-100, higher = more attractive/cheap; None if not computable
    method: str  # which technique produced this score - see module docstring
    detail: dict[str, float | None] = field(default_factory=dict)


def _saturating_score(value: float, sensitivity: float, *, invert: bool) -> float:
    if sensitivity == 0:
        return 50.0
    t = math.tanh(value / sensitivity)
    return 50.0 - 50.0 * t if invert else 50.0 + 50.0 * t


def _benchmark_rate_symbol(session: Session, macro_country: str) -> str | None:
    rate_country = _RATE_INSTRUMENT_COUNTRY_OVERRIDE.get(macro_country, macro_country)
    instruments = session.scalars(
        select(Instrument).where(
            Instrument.asset_class == AssetClass.RATE, Instrument.country == rate_country
        )
    ).all()
    for instrument in instruments:
        if (instrument.metadata_json or {}).get("tenor_years") == _BENCHMARK_TENOR_YEARS:
            return instrument.symbol
    return None


def _real_yield_for_country(session: Session, macro_country: str, as_of: dt.date) -> float | None:
    """Latest known benchmark (10Y) nominal yield minus latest known CPI for that
    country - both quantities are already on a comparable percentage-point scale in
    this platform's data model, so no unit conversion is needed.
    """
    symbol = _benchmark_rate_symbol(session, macro_country)
    if symbol is None:
        return None
    closes = point_in_time_closes(session, symbol, as_of=as_of, window_days=30)
    if not closes:
        return None
    nominal_yield = closes[-1][1]

    cpi_history = point_in_time_history(
        session, macro_country, "CPI_HEADLINE", as_of=as_of, window_days=400
    )
    if not cpi_history:
        return None
    cpi = cpi_history[-1][1]

    return nominal_yield - cpi


def _fx_valuation(session: Session, instrument: Instrument, *, as_of: dt.date) -> ValuationResult:
    config = load_yaml_config("signals")["valuation"]
    meta = instrument.metadata_json or {}
    base_ccy, quote_ccy = meta.get("base_currency"), meta.get("quote_currency")
    base_country = country_for_currency(base_ccy) if base_ccy else None
    quote_country = country_for_currency(quote_ccy) if quote_ccy else None
    if base_country is None or quote_country is None:
        return ValuationResult(score=None, method="fx_real_rate_differential")

    base_real = _real_yield_for_country(session, base_country, as_of)
    quote_real = _real_yield_for_country(session, quote_country, as_of)
    if base_real is None or quote_real is None:
        return ValuationResult(
            score=None,
            method="fx_real_rate_differential",
            detail={"base_real_yield": base_real, "quote_real_yield": quote_real},
        )

    differential = base_real - quote_real
    score = _saturating_score(differential, config["fx_sensitivity_pct"], invert=False)
    return ValuationResult(
        score=score,
        method="fx_real_rate_differential",
        detail={
            "base_real_yield": base_real,
            "quote_real_yield": quote_real,
            "differential_pct": differential,
        },
    )


def _rate_valuation(session: Session, instrument: Instrument, *, as_of: dt.date) -> ValuationResult:
    config = load_yaml_config("signals")["valuation"]
    if instrument.country is None:
        return ValuationResult(score=None, method="real_yield")

    macro_country = "EA" if instrument.country == "DE" else instrument.country
    closes = point_in_time_closes(session, instrument.symbol, as_of=as_of, window_days=30)
    if not closes:
        return ValuationResult(score=None, method="real_yield")
    nominal_yield = closes[-1][1]

    cpi_history = point_in_time_history(
        session, macro_country, "CPI_HEADLINE", as_of=as_of, window_days=400
    )
    if not cpi_history:
        return ValuationResult(
            score=None, method="real_yield", detail={"nominal_yield": nominal_yield}
        )
    cpi = cpi_history[-1][1]
    real_yield = nominal_yield - cpi

    score = _saturating_score(real_yield, config["rate_real_yield_sensitivity_pct"], invert=False)
    return ValuationResult(
        score=score,
        method="real_yield",
        detail={"nominal_yield": nominal_yield, "cpi": cpi, "real_yield": real_yield},
    )


def _equity_valuation(
    session: Session, instrument: Instrument, *, as_of: dt.date
) -> ValuationResult:
    config = load_yaml_config("signals")["valuation"]
    closes = [
        close
        for _, close in point_in_time_closes(
            session, instrument.symbol, as_of=as_of, window_days=config["equity_trend_window_days"]
        )
    ]
    if len(closes) < config["min_observations"]:
        return ValuationResult(score=None, method="trend_deviation_proxy")

    trend = sum(closes) / len(closes)
    if trend == 0:
        return ValuationResult(score=None, method="trend_deviation_proxy")

    deviation = closes[-1] / trend - 1
    # invert=True: price *above* its own long-run trend reads as "expensive", so a
    # positive deviation must lower the attractiveness-to-buy score.
    score = _saturating_score(deviation, config["equity_deviation_sensitivity"], invert=True)
    return ValuationResult(
        score=score,
        method="trend_deviation_proxy",
        detail={"price": closes[-1], "trend": trend, "deviation_pct": deviation},
    )


def _commodity_valuation(
    session: Session, instrument: Instrument, *, as_of: dt.date
) -> ValuationResult:
    config = load_yaml_config("signals")["valuation"]
    real_rate = _real_yield_for_country(session, "US", as_of)
    if real_rate is None:
        return ValuationResult(score=None, method="us_real_rate_sensitivity_proxy")

    # invert=True: low/negative real rates make non-yielding commodities relatively
    # more attractive, so a *higher* real rate must lower this score.
    score = _saturating_score(real_rate, config["commodity_real_rate_sensitivity_pct"], invert=True)
    return ValuationResult(
        score=score, method="us_real_rate_sensitivity_proxy", detail={"us_real_rate": real_rate}
    )


def compute_valuation(
    session: Session, instrument: Instrument, *, as_of: dt.date
) -> ValuationResult:
    if instrument.asset_class == AssetClass.FX:
        return _fx_valuation(session, instrument, as_of=as_of)
    if instrument.asset_class == AssetClass.RATE:
        return _rate_valuation(session, instrument, as_of=as_of)
    if instrument.asset_class == AssetClass.EQUITY_INDEX:
        return _equity_valuation(session, instrument, as_of=as_of)
    if instrument.asset_class == AssetClass.COMMODITY:
        return _commodity_valuation(session, instrument, as_of=as_of)
    return ValuationResult(score=None, method="unsupported_asset_class")
