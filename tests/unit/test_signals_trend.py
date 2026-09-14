from __future__ import annotations

import datetime as dt

from jlmacro.models.enums import AssetClass, Frequency
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.signals.trend import compute_trend


def _seed_instrument(db_session, symbol: str) -> Instrument:
    instrument = Instrument(
        symbol=symbol, name=symbol, asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add(instrument)
    db_session.flush()
    return instrument


def _insert_bar(
    db_session,
    instrument: Instrument,
    day: dt.date,
    close: float,
    *,
    revision_date: dt.date | None = None,
) -> None:
    db_session.add(
        MarketDataPoint(
            instrument_id=instrument.id,
            timestamp=dt.datetime.combine(day, dt.time(21, 0), tzinfo=dt.UTC),
            frequency=Frequency.DAILY,
            close=close,
            source="TEST",
            effective_date=day,
            release_date=day,
            revision_date=revision_date or day,
        )
    )


def _seed_trend_series(
    db_session, instrument: Instrument, n_days: int, start: float, daily_growth: float
) -> None:
    day = dt.date(2024, 1, 1)
    price = start
    for _ in range(n_days):
        _insert_bar(db_session, instrument, day, price)
        price *= 1 + daily_growth
        day += dt.timedelta(days=1)
    db_session.flush()


def test_compute_trend_none_below_min_observations(db_session):
    instrument = _seed_instrument(db_session, "TREND_SHORT")
    _seed_trend_series(db_session, instrument, 50, 100.0, 0.001)

    result = compute_trend(db_session, "TREND_SHORT", as_of=dt.date(2024, 2, 19))
    assert result.score is None
    assert result.label == "unknown"


def test_compute_trend_detects_strong_uptrend(db_session):
    instrument = _seed_instrument(db_session, "TREND_UP")
    _seed_trend_series(db_session, instrument, 260, 100.0, 0.006)  # steady ~0.6%/day grind up

    as_of = dt.date(2024, 1, 1) + dt.timedelta(days=259)
    result = compute_trend(db_session, "TREND_UP", as_of=as_of)

    assert result.score is not None
    assert result.score > 0
    assert result.label in {"long", "strong_long"}
    assert result.returns[20] is not None
    assert result.returns[20] > 0
    assert result.persistence is not None
    assert result.persistence > 0.9  # a steady daily grind should be highly persistent


def test_compute_trend_detects_strong_downtrend(db_session):
    instrument = _seed_instrument(db_session, "TREND_DOWN")
    _seed_trend_series(db_session, instrument, 260, 100.0, -0.006)

    as_of = dt.date(2024, 1, 1) + dt.timedelta(days=259)
    result = compute_trend(db_session, "TREND_DOWN", as_of=as_of)

    assert result.score is not None
    assert result.score < 0
    assert result.label in {"short", "strong_short"}


def test_compute_trend_flat_series_is_neutral(db_session):
    instrument = _seed_instrument(db_session, "TREND_FLAT")
    _seed_trend_series(db_session, instrument, 260, 100.0, 0.0)

    as_of = dt.date(2024, 1, 1) + dt.timedelta(days=259)
    result = compute_trend(db_session, "TREND_FLAT", as_of=as_of)

    assert result.score is not None
    assert abs(result.score) < 5.0
    assert result.label == "neutral"


def test_compute_trend_excludes_bar_not_yet_knowable(db_session):
    """A bar whose vintage (revision_date) is still in the future relative to
    `as_of` must be excluded, the same point-in-time discipline as the macro regime
    engine - see tests/unit/test_signals_pit.py for the underlying primitive.
    """
    instrument = _seed_instrument(db_session, "TREND_PIT")
    _seed_trend_series(db_session, instrument, 259, 100.0, 0.006)
    last_day = dt.date(2024, 1, 1) + dt.timedelta(days=258)

    # One more day's bar, with a distinct spike close, not knowable until 30 days
    # later (its vintage postdates the spike day itself).
    spike_day = last_day + dt.timedelta(days=1)
    db_session.add(
        MarketDataPoint(
            instrument_id=instrument.id,
            timestamp=dt.datetime.combine(spike_day, dt.time(21, 0), tzinfo=dt.UTC),
            frequency=Frequency.DAILY,
            close=9999.0,
            source="TEST",
            effective_date=spike_day,
            release_date=spike_day,
            revision_date=spike_day + dt.timedelta(days=30),
        )
    )
    db_session.flush()

    before_known = compute_trend(db_session, "TREND_PIT", as_of=spike_day)
    after_known = compute_trend(db_session, "TREND_PIT", as_of=spike_day + dt.timedelta(days=30))

    assert before_known.returns[20] != after_known.returns[20]
    assert after_known.returns[20] > before_known.returns[20]
