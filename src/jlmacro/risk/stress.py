"""Stress testing against config/scenarios.yaml.

Two kinds, both answering "what would happen to today's portfolio," never "what
will happen":

- Hypothetical scenarios (`apply_hypothetical_scenario`): apply an explicit shock
  (e.g. "equities down 20%", "rates up 100bp") to whichever instruments it can be
  honestly mapped onto. Several of the scenario file's shock keys describe things
  this platform's instrument universe has no direct handle on yet (a credit-spread
  index, an equity-vol percentile, a funding-stress percentile, an aggregate
  "commodities" or "growth" shock) - those are reported as `unmapped_shock_keys`,
  never silently dropped or guessed at, so a scenario's P&L is never presented as
  more complete than it actually is.
- Historical scenarios (`apply_historical_scenario`): replay today's weights against
  each instrument's actual point-in-time return over a named historical date range
  (e.g. 2008-09-01 to 2009-03-01). The mechanism is real; what it runs on, for now, is
  this platform's synthetic price history (no real market-data vendor exists yet -
  see README "Known limitations"), so the resulting P&L is illustrative of the
  *method*, not a genuine 2008 GFC replay, until real historical prices are wired in.

The rates_bp shock is converted from a yield-level shock (this platform stores RATE
instrument "close" as the yield level itself, e.g. 4.50 meaning 4.50%) into a price
return via `-tenor_years * (bp / 10000)` - the standard first-order bond-duration
approximation, using tenor as a duration proxy since there's no real modified-duration
figure in the data model. Documented as a proxy, not real duration.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.enums import AssetClass
from jlmacro.models.instrument import Instrument
from jlmacro.models.signals.pit import point_in_time_closes

_RECOGNISED_HYPOTHETICAL_KEYS = {"equity_indices", "rates_bp", "usd_index", "audusd", "oil", "gold"}
_OIL_SYMBOLS = ("WTI", "BRENT")
_GOLD_SYMBOL = "XAU"
_AUDUSD_SYMBOL = "AUDUSD"


@dataclass
class HypotheticalStressResult:
    scenario_id: str
    pnl_pct: float
    pnl_amount: float
    instrument_shocks: dict[str, float] = field(default_factory=dict)
    unmapped_shock_keys: list[str] = field(default_factory=list)


@dataclass
class HistoricalStressResult:
    scenario_id: str
    start_date: dt.date
    end_date: dt.date
    pnl_pct: float
    pnl_amount: float
    instrument_returns: dict[str, float] = field(default_factory=dict)
    missing_symbols: list[str] = field(default_factory=list)


def _find_scenario(scenarios: list[dict], scenario_id: str) -> dict:
    for scenario in scenarios:
        if scenario["id"] == scenario_id:
            return scenario
    raise ValueError(f"unknown scenario id: {scenario_id}")


def _instrument_lookup(session: Session, symbols: list[str]) -> dict[str, Instrument]:
    rows = session.execute(select(Instrument).where(Instrument.symbol.in_(symbols))).scalars()
    return {row.symbol: row for row in rows}


def apply_hypothetical_scenario(
    session: Session, weights: pd.Series, scenario_id: str, *, nav: float
) -> HypotheticalStressResult:
    scenarios = load_yaml_config("scenarios")["hypothetical_scenarios"]
    scenario = _find_scenario(scenarios, scenario_id)
    shocks: dict[str, float] = scenario["shocks"]

    instruments = _instrument_lookup(session, list(weights.index))
    instrument_shocks: dict[str, float] = {}
    unmapped_keys: list[str] = []

    for key, value in shocks.items():
        if key not in _RECOGNISED_HYPOTHETICAL_KEYS:
            unmapped_keys.append(key)
            continue

        if key == "equity_indices":
            for symbol, instrument in instruments.items():
                if instrument.asset_class == AssetClass.EQUITY_INDEX:
                    instrument_shocks[symbol] = value

        elif key == "rates_bp":
            for symbol, instrument in instruments.items():
                if instrument.asset_class == AssetClass.RATE:
                    tenor_years = float((instrument.metadata_json or {}).get("tenor_years", 5))
                    instrument_shocks[symbol] = -tenor_years * (value / 10_000.0)

        elif key == "usd_index":
            for symbol, instrument in instruments.items():
                if instrument.asset_class != AssetClass.FX:
                    continue
                meta = instrument.metadata_json or {}
                if meta.get("quote_currency") == "USD":
                    instrument_shocks[symbol] = -value
                elif meta.get("base_currency") == "USD":
                    instrument_shocks[symbol] = value

        elif key == "audusd" and _AUDUSD_SYMBOL in instruments:
            instrument_shocks[_AUDUSD_SYMBOL] = value

        elif key == "oil":
            for symbol in _OIL_SYMBOLS:
                if symbol in instruments:
                    instrument_shocks[symbol] = value

        elif key == "gold" and _GOLD_SYMBOL in instruments:
            instrument_shocks[_GOLD_SYMBOL] = value

    pnl_pct = sum(
        float(weights.get(symbol, 0.0)) * shock for symbol, shock in instrument_shocks.items()
    )

    return HypotheticalStressResult(
        scenario_id=scenario_id,
        pnl_pct=pnl_pct,
        pnl_amount=pnl_pct * nav,
        instrument_shocks={s: v for s, v in instrument_shocks.items() if s in weights.index},
        unmapped_shock_keys=unmapped_keys,
    )


def apply_historical_scenario(
    session: Session, weights: pd.Series, scenario_id: str, *, nav: float
) -> HistoricalStressResult:
    scenarios = load_yaml_config("scenarios")["historical_scenarios"]
    scenario = _find_scenario(scenarios, scenario_id)
    start_date = dt.date.fromisoformat(scenario["start_date"])
    end_date = dt.date.fromisoformat(scenario["end_date"])
    window_days = (end_date - start_date).days + 30

    instrument_returns: dict[str, float] = {}
    missing_symbols: list[str] = []

    for symbol in weights.index:
        history = point_in_time_closes(session, symbol, as_of=end_date, window_days=window_days)
        in_window = [(d, c) for d, c in history if start_date <= d <= end_date]
        if len(in_window) < 2:
            missing_symbols.append(symbol)
            continue
        first_close = in_window[0][1]
        last_close = in_window[-1][1]
        instrument_returns[symbol] = (last_close / first_close) - 1.0

    pnl_pct = sum(
        float(weights.get(symbol, 0.0)) * ret for symbol, ret in instrument_returns.items()
    )

    return HistoricalStressResult(
        scenario_id=scenario_id,
        start_date=start_date,
        end_date=end_date,
        pnl_pct=pnl_pct,
        pnl_amount=pnl_pct * nav,
        instrument_returns=instrument_returns,
        missing_symbols=missing_symbols,
    )
