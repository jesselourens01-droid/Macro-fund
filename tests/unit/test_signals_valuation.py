from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.models.enums import AssetClass, Frequency, MacroCategory
from jlmacro.models.instrument import Instrument
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.signals.valuation import compute_valuation


def _insert_cpi(db_session, country: str, effective_date: dt.date, value: float) -> None:
    db_session.add(
        MacroDataPoint(
            country=country,
            indicator_code="CPI_HEADLINE",
            category=MacroCategory.INFLATION,
            frequency=Frequency.MONTHLY,
            value=value,
            original_value=value,
            source="TEST",
            effective_date=effective_date,
            release_date=effective_date,
            revision_date=effective_date,
        )
    )


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


def test_rate_valuation_higher_real_yield_is_more_attractive(db_session):
    instrument = Instrument(
        symbol="TEST10Y", name="Test 10Y", asset_class=AssetClass.RATE, country="US", currency="USD"
    )
    db_session.add(instrument)
    db_session.flush()

    day = dt.date(2024, 6, 30)
    _insert_bar(db_session, instrument, day, 5.0)  # nominal yield 5%
    _insert_cpi(db_session, "US", day, 2.0)  # CPI 2% -> real yield 3%
    db_session.flush()

    result = compute_valuation(db_session, instrument, as_of=day)
    assert result.method == "real_yield"
    assert result.score is not None
    assert result.score > 50.0
    assert result.detail["real_yield"] == pytest.approx(3.0)


def test_rate_valuation_negative_real_yield_is_unattractive(db_session):
    instrument = Instrument(
        symbol="TEST10Y2",
        name="Test 10Y 2",
        asset_class=AssetClass.RATE,
        country="US",
        currency="USD",
    )
    db_session.add(instrument)
    db_session.flush()

    day = dt.date(2024, 6, 30)
    _insert_bar(db_session, instrument, day, 2.0)
    _insert_cpi(db_session, "US", day, 5.0)  # real yield -3%
    db_session.flush()

    result = compute_valuation(db_session, instrument, as_of=day)
    assert result.score is not None
    assert result.score < 50.0


def test_rate_valuation_none_without_cpi(db_session):
    instrument = Instrument(
        symbol="TEST10Y3",
        name="Test 10Y 3",
        asset_class=AssetClass.RATE,
        country="ZZ",
        currency="ZZZ",
    )
    db_session.add(instrument)
    db_session.flush()
    _insert_bar(db_session, instrument, dt.date(2024, 6, 30), 5.0)
    db_session.flush()

    result = compute_valuation(db_session, instrument, as_of=dt.date(2024, 6, 30))
    assert result.score is None


def test_fx_valuation_favours_higher_real_yield_base_currency(db_session):
    us_rate = Instrument(
        symbol="USRATE10Y",
        name="US 10Y",
        asset_class=AssetClass.RATE,
        country="US",
        currency="USD",
        metadata_json={"tenor_years": 10},
    )
    au_rate = Instrument(
        symbol="AURATE10Y",
        name="AU 10Y",
        asset_class=AssetClass.RATE,
        country="AU",
        currency="AUD",
        metadata_json={"tenor_years": 10},
    )
    fx = Instrument(
        symbol="AUDUSD_TEST",
        name="AUD/USD test",
        asset_class=AssetClass.FX,
        currency="USD",
        metadata_json={"base_currency": "AUD", "quote_currency": "USD"},
    )
    db_session.add_all([us_rate, au_rate, fx])
    db_session.flush()

    day = dt.date(2024, 6, 30)
    _insert_bar(db_session, us_rate, day, 4.0)
    _insert_cpi(db_session, "US", day, 3.0)  # US real yield 1%
    _insert_bar(db_session, au_rate, day, 5.0)
    _insert_cpi(db_session, "AU", day, 2.0)  # AU real yield 3% - higher than US
    db_session.flush()

    result = compute_valuation(db_session, fx, as_of=day)
    assert result.method == "fx_real_rate_differential"
    assert result.score is not None
    assert result.score > 50.0  # AUD's real yield advantage makes AUDUSD attractive to be long


def test_fx_valuation_none_for_unmapped_currency(db_session):
    fx = Instrument(
        symbol="NZDCAD_TEST",
        name="NZD/CAD test",
        asset_class=AssetClass.FX,
        currency="CAD",
        metadata_json={"base_currency": "NZD", "quote_currency": "CAD"},
    )
    db_session.add(fx)
    db_session.flush()

    result = compute_valuation(db_session, fx, as_of=dt.date(2024, 6, 30))
    assert result.score is None  # neither NZD nor CAD map to a tracked macro country


def test_equity_valuation_above_trend_is_less_attractive(db_session):
    instrument = Instrument(
        symbol="TESTEQ", name="Test Equity", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add(instrument)
    db_session.flush()

    day = dt.date(2024, 1, 1)
    for i in range(100):
        _insert_bar(db_session, instrument, day + dt.timedelta(days=i), 100.0)
    # Sharp recent rally well above the flat trend.
    _insert_bar(db_session, instrument, day + dt.timedelta(days=100), 150.0)
    db_session.flush()

    result = compute_valuation(db_session, instrument, as_of=day + dt.timedelta(days=100))
    assert result.method == "trend_deviation_proxy"
    assert result.score is not None
    assert result.score < 50.0  # richer than its own trend -> less attractive


def test_commodity_valuation_low_real_rate_is_attractive(db_session):
    us_rate = Instrument(
        symbol="USRATE10Y2",
        name="US 10Y 2",
        asset_class=AssetClass.RATE,
        country="US",
        currency="USD",
        metadata_json={"tenor_years": 10},
    )
    gold = Instrument(
        symbol="TESTGOLD", name="Test Gold", asset_class=AssetClass.COMMODITY, currency="USD"
    )
    db_session.add_all([us_rate, gold])
    db_session.flush()

    day = dt.date(2024, 6, 30)
    _insert_bar(db_session, us_rate, day, 1.0)
    _insert_cpi(db_session, "US", day, 4.0)  # real yield -3% -> low/negative
    db_session.flush()

    result = compute_valuation(db_session, gold, as_of=day)
    assert result.method == "us_real_rate_sensitivity_proxy"
    assert result.score is not None
    assert result.score > 50.0
