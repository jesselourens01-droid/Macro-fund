from __future__ import annotations

import datetime as dt

from jlmacro.models.enums import AssetClass, Frequency
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.signals.pit import point_in_time_closes


def test_point_in_time_closes_excludes_bar_not_yet_knowable(db_session):
    instrument = Instrument(
        symbol="PIT_MKT", name="PIT", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add(instrument)
    db_session.flush()

    day = dt.date(2024, 6, 3)
    db_session.add(
        MarketDataPoint(
            instrument_id=instrument.id,
            timestamp=dt.datetime.combine(day, dt.time(21, 0), tzinfo=dt.UTC),
            frequency=Frequency.DAILY,
            close=123.45,
            source="TEST",
            effective_date=day,
            release_date=day,
            revision_date=day + dt.timedelta(days=10),  # only knowable 10 days later
        )
    )
    db_session.flush()

    before = point_in_time_closes(db_session, "PIT_MKT", as_of=day, window_days=30)
    assert before == []

    after = point_in_time_closes(
        db_session, "PIT_MKT", as_of=day + dt.timedelta(days=10), window_days=30
    )
    assert after == [(day, 123.45)]


def test_point_in_time_closes_respects_window(db_session):
    instrument = Instrument(
        symbol="PIT_MKT2", name="PIT2", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add(instrument)
    db_session.flush()

    for offset in range(0, 100, 10):
        day = dt.date(2024, 1, 1) + dt.timedelta(days=offset)
        db_session.add(
            MarketDataPoint(
                instrument_id=instrument.id,
                timestamp=dt.datetime.combine(day, dt.time(21, 0), tzinfo=dt.UTC),
                frequency=Frequency.DAILY,
                close=float(offset),
                source="TEST",
                effective_date=day,
                release_date=day,
                revision_date=day,
            )
        )
    db_session.flush()

    as_of = dt.date(2024, 1, 1) + dt.timedelta(days=90)
    closes = point_in_time_closes(db_session, "PIT_MKT2", as_of=as_of, window_days=30)
    days = [day for day, _ in closes]
    assert dt.date(2024, 1, 1) + dt.timedelta(days=90) in days
    assert dt.date(2024, 1, 1) not in days  # outside the 30-day window
