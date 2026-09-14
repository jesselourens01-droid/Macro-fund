from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from jlmacro.models.enums import AssetClass, Frequency
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.risk.stress import apply_historical_scenario, apply_hypothetical_scenario


def _seed_instrument(
    db_session,
    symbol: str,
    asset_class: AssetClass,
    currency: str,
    *,
    metadata: dict | None = None,
) -> Instrument:
    instrument = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        currency=currency,
        metadata_json=metadata,
    )
    db_session.add(instrument)
    db_session.flush()
    return instrument


def _insert_bar(db_session, instrument: Instrument, day: dt.date, close: float) -> None:
    db_session.add(
        MarketDataPoint(
            instrument_id=instrument.id,
            timestamp=dt.datetime.combine(day, dt.time(21, 0), tzinfo=dt.UTC),
            frequency=Frequency.DAILY,
            close=close,
            source="TEST",
            effective_date=day,
            release_date=day,
            revision_date=day,
        )
    )


def test_hypothetical_equity_shock_hits_only_equity_positions(db_session):
    _seed_instrument(db_session, "SPXT", AssetClass.EQUITY_INDEX, "USD")
    _seed_instrument(db_session, "US10YT", AssetClass.RATE, "USD", metadata={"tenor_years": 10})
    db_session.flush()

    weights = pd.Series({"SPXT": 0.4, "US10YT": 0.3})
    result = apply_hypothetical_scenario(db_session, weights, "EQUITIES_DOWN_20", nav=1_000_000.0)

    assert result.instrument_shocks == {"SPXT": -0.20}
    assert result.pnl_pct == pytest.approx(0.4 * -0.20)
    assert result.unmapped_shock_keys == []


def test_hypothetical_rates_shock_uses_tenor_as_duration_proxy(db_session):
    _seed_instrument(db_session, "US10YT2", AssetClass.RATE, "USD", metadata={"tenor_years": 10})
    db_session.flush()

    weights = pd.Series({"US10YT2": 1.0})
    result = apply_hypothetical_scenario(db_session, weights, "RATES_UP_100BP", nav=1_000_000.0)

    # -tenor_years * (bp / 10000) = -10 * (100/10000) = -0.10
    assert result.instrument_shocks["US10YT2"] == pytest.approx(-0.10)
    assert result.pnl_pct == pytest.approx(-0.10)


def test_hypothetical_usd_index_shock_direction_depends_on_quote_vs_base(db_session):
    _seed_instrument(
        db_session,
        "EURUSDT",
        AssetClass.FX,
        "USD",
        metadata={"base_currency": "EUR", "quote_currency": "USD"},
    )
    _seed_instrument(
        db_session,
        "USDJPYT",
        AssetClass.FX,
        "JPY",
        metadata={"base_currency": "USD", "quote_currency": "JPY"},
    )
    db_session.flush()

    weights = pd.Series({"EURUSDT": 0.5, "USDJPYT": 0.5})
    result = apply_hypothetical_scenario(db_session, weights, "USD_UP_10", nav=1_000_000.0)

    assert result.instrument_shocks["EURUSDT"] == pytest.approx(-0.10)  # EUR/USD falls
    assert result.instrument_shocks["USDJPYT"] == pytest.approx(0.10)  # USD/JPY rises


def test_hypothetical_gold_and_oil_shocks(db_session):
    _seed_instrument(db_session, "XAU", AssetClass.COMMODITY, "USD")
    _seed_instrument(db_session, "WTI", AssetClass.COMMODITY, "USD")
    db_session.flush()

    weights = pd.Series({"XAU": 0.2, "WTI": 0.1})
    gold_result = apply_hypothetical_scenario(db_session, weights, "GOLD_UP_20", nav=1_000_000.0)
    oil_result = apply_hypothetical_scenario(db_session, weights, "OIL_UP_40", nav=1_000_000.0)

    assert gold_result.instrument_shocks == {"XAU": 0.20}
    assert oil_result.instrument_shocks == {"WTI": 0.40}


def test_hypothetical_scenario_reports_unmapped_shock_keys_honestly(db_session):
    weights = pd.Series({"ANYTHING": 1.0})
    result = apply_hypothetical_scenario(db_session, weights, "CHINA_HARD_LANDING", nav=1_000_000.0)

    assert result.pnl_pct == 0.0
    assert set(result.unmapped_shock_keys) == {"china_growth", "commodities", "aud"}


def test_hypothetical_scenario_unknown_id_raises():
    with pytest.raises(ValueError, match="unknown scenario"):
        apply_hypothetical_scenario(None, pd.Series({"A": 1.0}), "NOT_A_REAL_SCENARIO", nav=1.0)


def test_historical_scenario_replays_actual_pit_returns_over_the_window(db_session):
    instrument = _seed_instrument(db_session, "GFCTEST", AssetClass.EQUITY_INDEX, "USD")
    start = dt.date(2008, 9, 1)
    end = dt.date(2009, 3, 1)
    _insert_bar(db_session, instrument, start, 100.0)
    _insert_bar(db_session, instrument, start + dt.timedelta(days=90), 60.0)
    _insert_bar(db_session, instrument, end, 55.0)
    db_session.flush()

    weights = pd.Series({"GFCTEST": 0.5})
    result = apply_historical_scenario(db_session, weights, "GFC_2008", nav=1_000_000.0)

    assert result.instrument_returns["GFCTEST"] == pytest.approx(55.0 / 100.0 - 1.0)
    assert result.pnl_pct == pytest.approx(0.5 * (55.0 / 100.0 - 1.0))
    assert result.missing_symbols == []


def test_historical_scenario_reports_missing_symbols_without_data_in_window(db_session):
    _seed_instrument(db_session, "NODATA", AssetClass.EQUITY_INDEX, "USD")
    db_session.flush()

    weights = pd.Series({"NODATA": 1.0})
    result = apply_historical_scenario(db_session, weights, "GFC_2008", nav=1_000_000.0)

    assert result.missing_symbols == ["NODATA"]
    assert result.pnl_pct == 0.0
