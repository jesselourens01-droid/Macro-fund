from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.models.enums import Frequency, MacroCategory
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.regime.scoring import point_in_time_history, rolling_zscore, zscore_momentum


def _insert(
    db_session,
    effective_date: dt.date,
    value: float,
    *,
    release_date: dt.date | None = None,
    revision_date: dt.date | None = None,
    country: str = "US",
    indicator_code: str = "TEST_SCORING_IND",
) -> None:
    release_date = release_date or effective_date
    revision_date = revision_date or release_date
    db_session.add(
        MacroDataPoint(
            country=country,
            indicator_code=indicator_code,
            category=MacroCategory.GROWTH,
            frequency=Frequency.MONTHLY,
            value=value,
            original_value=value,
            source="TEST",
            effective_date=effective_date,
            release_date=release_date,
            revision_date=revision_date,
        )
    )
    db_session.flush()


def _month_end(year: int, month: int) -> dt.date:
    import calendar

    return dt.date(year, month, calendar.monthrange(year, month)[1])


def test_point_in_time_history_excludes_future_revisions(db_session):
    period = _month_end(2024, 1)
    # First release: known from Feb 2024.
    _insert(
        db_session,
        period,
        100.0,
        release_date=_month_end(2024, 2),
        revision_date=_month_end(2024, 2),
    )
    # A much later revision that changes the value drastically - only knowable much later.
    _insert(
        db_session,
        period,
        999.0,
        release_date=_month_end(2024, 2),
        revision_date=_month_end(2024, 12),
    )

    as_of_before_revision = _month_end(2024, 6)
    history = point_in_time_history(
        db_session, "US", "TEST_SCORING_IND", as_of=as_of_before_revision, window_days=3650
    )
    assert history == [(period, 100.0)]

    as_of_after_revision = _month_end(2025, 1)
    history_after = point_in_time_history(
        db_session, "US", "TEST_SCORING_IND", as_of=as_of_after_revision, window_days=3650
    )
    assert history_after == [(period, 999.0)]


def test_point_in_time_history_respects_window(db_session):
    for i in range(1, 13):
        _insert(db_session, _month_end(2024, i), float(i))

    as_of = _month_end(2024, 12)
    history = point_in_time_history(
        db_session, "US", "TEST_SCORING_IND", as_of=as_of, window_days=90
    )
    periods = [p for p, _ in history]
    assert _month_end(2024, 12) in periods
    assert _month_end(2024, 1) not in periods  # outside the 90-day window


def test_rolling_zscore_returns_none_below_min_observations(db_session):
    for i in range(1, 6):  # fewer than the configured min_observations (12)
        _insert(db_session, _month_end(2024, i), float(i))

    z = rolling_zscore(db_session, "US", "TEST_SCORING_IND", as_of=_month_end(2024, 5))
    assert z is None


def test_rolling_zscore_positive_for_latest_high_value(db_session):
    for i in range(1, 13):
        _insert(db_session, _month_end(2024, i), 50.0)
    _insert(db_session, _month_end(2025, 1), 500.0)

    z = rolling_zscore(db_session, "US", "TEST_SCORING_IND", as_of=_month_end(2025, 1))
    assert z is not None
    assert z > 0


def test_rolling_zscore_zero_when_constant(db_session):
    for i in range(1, 14):
        _insert(db_session, _month_end(2024, i) if i <= 12 else _month_end(2025, 1), 42.0)

    z = rolling_zscore(db_session, "US", "TEST_SCORING_IND", as_of=_month_end(2025, 1))
    assert z == pytest.approx(0.0)


def test_zscore_momentum_none_with_insufficient_history(db_session):
    for i in range(1, 13):
        _insert(db_session, _month_end(2024, i), float(i))

    momentum = zscore_momentum(db_session, "US", "TEST_SCORING_IND", as_of=_month_end(2024, 12))
    assert momentum is None


def test_zscore_momentum_detects_acceleration(db_session):
    # Flat for a year, then a sharp recent jump - z-score should be rising into the
    # most recent periods relative to a few periods earlier.
    for i in range(1, 13):
        _insert(db_session, _month_end(2024, i), 50.0)
    _insert(db_session, _month_end(2025, 1), 50.0)
    _insert(db_session, _month_end(2025, 2), 50.0)
    _insert(db_session, _month_end(2025, 3), 500.0)

    momentum = zscore_momentum(db_session, "US", "TEST_SCORING_IND", as_of=_month_end(2025, 3))
    assert momentum is not None
    assert momentum > 0
