from __future__ import annotations

import datetime as dt

from jlmacro.models.enums import AssetClass, Frequency
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.signals.positioning import compute_positioning


def _seed_instrument(db_session, symbol: str) -> Instrument:
    instrument = Instrument(
        symbol=symbol, name=symbol, asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add(instrument)
    db_session.flush()
    return instrument


def _insert_series(db_session, instrument: Instrument, closes: list[float]) -> None:
    day = dt.date(2024, 1, 1)
    for close in closes:
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
        day += dt.timedelta(days=1)
    db_session.flush()


def test_positioning_none_below_min_observations(db_session):
    instrument = _seed_instrument(db_session, "POS_SHORT")
    _insert_series(db_session, instrument, [100.0] * 10)

    as_of = dt.date(2024, 1, 1) + dt.timedelta(days=9)
    result = compute_positioning(db_session, "POS_SHORT", as_of=as_of)
    assert result.score is None
    assert result.label == "unknown"


def test_positioning_relentless_rally_is_extreme_long(db_session):
    instrument = _seed_instrument(db_session, "POS_UP")
    closes = [100.0 + i for i in range(40)]  # straight-line up move, no down days
    _insert_series(db_session, instrument, closes)

    as_of = dt.date(2024, 1, 1) + dt.timedelta(days=39)
    result = compute_positioning(db_session, "POS_UP", as_of=as_of)

    assert result.rsi is not None
    assert result.rsi > 90
    assert result.label == "extreme_long"
    assert result.score is not None
    assert result.score < 20  # contrarian framing: overbought lowers the score


def test_positioning_relentless_selloff_is_extreme_short(db_session):
    instrument = _seed_instrument(db_session, "POS_DOWN")
    closes = [140.0 - i for i in range(40)]
    _insert_series(db_session, instrument, closes)

    as_of = dt.date(2024, 1, 1) + dt.timedelta(days=39)
    result = compute_positioning(db_session, "POS_DOWN", as_of=as_of)

    assert result.rsi is not None
    assert result.rsi < 10
    assert result.label == "extreme_short"
    assert result.score is not None
    assert result.score > 80  # contrarian framing: oversold raises the score


def test_positioning_choppy_flat_series_is_neutral(db_session):
    instrument = _seed_instrument(db_session, "POS_FLAT")
    closes = [100.0, 101.0, 99.5, 100.5, 99.8, 100.2] * 10
    _insert_series(db_session, instrument, closes)

    as_of = dt.date(2024, 1, 1) + dt.timedelta(days=len(closes) - 1)
    result = compute_positioning(db_session, "POS_FLAT", as_of=as_of)

    assert result.label == "neutral"
