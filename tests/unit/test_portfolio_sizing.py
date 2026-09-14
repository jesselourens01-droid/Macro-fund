from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.config import load_yaml_config
from jlmacro.models.enums import AssetClass, Frequency
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.portfolio.sizing import compute_position_size, risk_pct_for_units


def _seed_instrument(db_session, symbol: str) -> Instrument:
    instrument = Instrument(
        symbol=symbol, name=symbol, asset_class=AssetClass.EQUITY_INDEX, currency="USD"
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


@pytest.mark.parametrize(
    ("risk_units", "config_key"),
    [(0.5, "normal_min"), (1.0, "normal_max"), (1.5, "high_conviction_max")],
)
def test_risk_pct_for_units_matches_config(risk_units, config_key):
    expected = load_yaml_config("risk_limits")["position_risk"][config_key]
    assert risk_pct_for_units(risk_units) == expected


def test_risk_pct_for_units_fails_safe_to_zero_for_unrecognised_units():
    assert risk_pct_for_units(0.0) == 0.0
    assert risk_pct_for_units(2.7) == 0.0


def test_compute_position_size_scales_linearly_with_risk_units(db_session):
    instrument = _seed_instrument(db_session, "SIZEA")
    start = dt.date(2024, 1, 1)
    # The trend engine's min_observations (config/signals.yaml) is 210, so ATR isn't
    # computable on a shorter history - seed comfortably past that.
    num_days = 230
    for i in range(num_days):
        close = 100.0 + i + (1.0 if i % 2 == 0 else -1.0)
        _insert_bar(db_session, instrument, start + dt.timedelta(days=i), close)
    db_session.flush()
    as_of = start + dt.timedelta(days=num_days - 1)

    half = compute_position_size(
        db_session, "SIZEA", nav=10_000_000.0, risk_units=0.5, direction=1, as_of=as_of
    )
    full = compute_position_size(
        db_session, "SIZEA", nav=10_000_000.0, risk_units=1.0, direction=1, as_of=as_of
    )
    high = compute_position_size(
        db_session, "SIZEA", nav=10_000_000.0, risk_units=1.5, direction=1, as_of=as_of
    )

    assert half.stop_distance_pct == pytest.approx(full.stop_distance_pct)
    assert full.risk_budget == pytest.approx(half.risk_budget * 2)
    assert high.risk_budget == pytest.approx(half.risk_budget * 3)
    assert full.notional == pytest.approx(half.notional * 2)
    assert high.notional is not None and half.notional is not None
    assert high.notional > full.notional > half.notional


def test_compute_position_size_zero_risk_units_yields_no_notional(db_session):
    instrument = _seed_instrument(db_session, "SIZEB")
    start = dt.date(2024, 1, 1)
    for i in range(60):
        _insert_bar(db_session, instrument, start + dt.timedelta(days=i), 100.0 + i)
    db_session.flush()

    result = compute_position_size(
        db_session,
        "SIZEB",
        nav=10_000_000.0,
        risk_units=0.0,
        direction=1,
        as_of=start + dt.timedelta(days=59),
    )

    assert result.risk_budget == 0.0
    assert result.notional is None


def test_compute_position_size_without_price_history_yields_no_notional(db_session):
    _seed_instrument(db_session, "SIZEC")
    db_session.flush()

    result = compute_position_size(
        db_session,
        "SIZEC",
        nav=10_000_000.0,
        risk_units=1.0,
        direction=1,
        as_of=dt.date(2024, 6, 30),
    )

    assert result.price is None
    assert result.stop_distance_pct is None
    assert result.notional is None
