from __future__ import annotations

import datetime as dt

from jlmacro.models.enums import Frequency, MacroCategory
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.signals.catalyst import catalyst_score, indicator_surprise, upcoming_catalysts


def _insert(
    db_session,
    country: str,
    indicator_code: str,
    effective_date: dt.date,
    release_date: dt.date,
    value: float,
) -> None:
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
            revision_date=release_date,
        )
    )
    db_session.flush()


def test_upcoming_catalysts_projects_next_release_from_cadence(db_session):
    # A monthly indicator released ~14 days after each month-end, for 6 months.
    for month in range(1, 7):
        effective = dt.date(2024, month, 28)
        release = effective + dt.timedelta(days=14)
        _insert(db_session, "US", "PMI_MFG", effective, release, 50.0 + month)

    last_release = dt.date(2024, 6, 28) + dt.timedelta(days=14)
    as_of = last_release + dt.timedelta(days=1)

    events = upcoming_catalysts(db_session, "US", as_of=as_of, window_days=45)
    matching = [e for e in events if e.indicator_code == "PMI_MFG"]
    assert len(matching) == 1

    # Projection is median-gap-based, not a naive fixed-30-day cadence, so pin it to
    # "next month, +/- a day or two" rather than an exact calendar date (real months
    # aren't a fixed number of days).
    event = matching[0]
    assert dt.date(2024, 7, 27) <= event.projected_effective_date <= dt.date(2024, 7, 30)
    assert (event.projected_release_date - event.projected_effective_date).days == 14


def test_upcoming_catalysts_excludes_events_outside_window(db_session):
    for month in range(1, 4):
        effective = dt.date(2024, month, 28)
        release = effective + dt.timedelta(days=14)
        _insert(db_session, "US", "PMI_MFG", effective, release, 50.0)

    as_of = dt.date(2024, 3, 28) + dt.timedelta(days=14) + dt.timedelta(days=1)
    events = upcoming_catalysts(
        db_session, "US", as_of=as_of, window_days=5
    )  # too short to catch next month's release
    assert not any(e.indicator_code == "PMI_MFG" for e in events)


def test_upcoming_catalysts_needs_at_least_two_periods(db_session):
    _insert(db_session, "US", "PMI_MFG", dt.date(2024, 1, 28), dt.date(2024, 2, 11), 50.0)
    events = upcoming_catalysts(db_session, "US", as_of=dt.date(2024, 2, 15), window_days=30)
    assert not any(e.indicator_code == "PMI_MFG" for e in events)


def test_indicator_surprise_reuses_rolling_zscore(db_session):
    for month in range(1, 13):
        _insert(
            db_session,
            "US",
            "PMI_MFG",
            dt.date(2024, month, 28),
            dt.date(2024, month, 28) + dt.timedelta(days=14),
            50.0,
        )
    _insert(
        db_session,
        "US",
        "PMI_MFG",
        dt.date(2025, 1, 28),
        dt.date(2025, 1, 28) + dt.timedelta(days=14),
        65.0,
    )

    surprise = indicator_surprise(
        db_session, "US", "PMI_MFG", as_of=dt.date(2025, 1, 28) + dt.timedelta(days=14)
    )
    assert surprise is not None
    assert surprise > 0


def test_catalyst_score_neutral_without_any_data(db_session):
    result = catalyst_score(db_session, "ZZ", as_of=dt.date(2024, 6, 1))
    assert result.score == 50.0
    assert result.average_surprise is None
    assert result.upcoming_events == []
