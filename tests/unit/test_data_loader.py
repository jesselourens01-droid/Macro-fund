from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.data.base import BaseMacroDataProvider
from jlmacro.data.loader import (
    ingest_macro_vintage_records,
    ingest_snapshot_macro_data,
    seed_instruments,
    seed_macro_data,
    seed_market_data,
)
from jlmacro.models.macro_data import MacroDataPoint


def test_seed_instruments_from_config(db_session):
    instruments = seed_instruments(db_session)
    assert len(instruments) > 20
    symbols = {i.symbol for i in instruments}
    assert "SPX" in symbols
    assert "EURUSD" in symbols
    assert "XAU" in symbols
    assert "US10Y" in symbols


def test_seed_instruments_is_idempotent(db_session):
    first = seed_instruments(db_session)
    second = seed_instruments(db_session)
    assert len(first) == len(second)


def test_seed_market_data_and_idempotency(db_session):
    instruments = seed_instruments(db_session)
    start, end = dt.date(2026, 1, 1), dt.date(2026, 2, 1)

    inserted_first = seed_market_data(db_session, instruments, start=start, end=end)
    assert inserted_first > 0

    inserted_second = seed_market_data(db_session, instruments, start=start, end=end)
    assert inserted_second == 0


def test_seed_macro_data_and_idempotency(db_session):
    seed_instruments(db_session)
    start, end = dt.date(2026, 1, 1), dt.date(2026, 6, 1)

    inserted_first = seed_macro_data(db_session, start=start, end=end)
    assert inserted_first > 0

    inserted_second = seed_macro_data(db_session, start=start, end=end)
    assert inserted_second == 0


def _vintage_record(effective_date, revision_date, value, *, original=None, revised=None):
    return {
        "country": "US",
        "indicator_code": "TEST_LOADER_CPI",
        "category": "inflation",
        "frequency": "monthly",
        "effective_date": effective_date,
        "release_date": revision_date,
        "revision_date": revision_date,
        "value": value,
        "original_value": original if original is not None else value,
        "revised_value": revised,
        "source": "TEST",
    }


def test_ingest_macro_vintage_records_is_idempotent(db_session):
    records = [_vintage_record(dt.date(2024, 1, 31), dt.date(2024, 2, 14), 3.0)]

    first = ingest_macro_vintage_records(db_session, records)
    assert first == 1

    second = ingest_macro_vintage_records(db_session, records)
    assert second == 0


def test_ingest_macro_vintage_records_inserts_distinct_revisions(db_session):
    records = [
        _vintage_record(dt.date(2024, 1, 31), dt.date(2024, 2, 14), 3.0),
        _vintage_record(dt.date(2024, 1, 31), dt.date(2024, 3, 14), 3.2, original=3.0, revised=3.2),
    ]
    inserted = ingest_macro_vintage_records(db_session, records)
    assert inserted == 2


class _FakeSnapshotProvider(BaseMacroDataProvider):
    name = "FAKE_SNAPSHOT"

    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def fetch(self, *, identifiers, start, end, countries=None, **kwargs):
        return self._records


def _snapshot_record(effective_date, value):
    return {
        "country": "AU",
        "indicator_code": "TEST_SNAPSHOT_RATE",
        "category": "monetary_policy",
        "frequency": "daily",
        "effective_date": effective_date,
        "release_date": None,
        "revision_date": None,
        "value": value,
        "original_value": None,
        "revised_value": None,
        "source": "FAKE_SNAPSHOT",
    }


def test_ingest_snapshot_macro_data_creates_revision_only_on_change(db_session):
    period = dt.date(2024, 6, 1)
    day1, day2, day3 = dt.date(2024, 6, 1), dt.date(2024, 6, 2), dt.date(2024, 6, 3)

    # First ingest: brand new value -> one row, release_date == revision_date == day1.
    provider = _FakeSnapshotProvider([_snapshot_record(period, 4.35)])
    changed = ingest_snapshot_macro_data(
        db_session, provider, countries=["AU"], start=period, end=period, as_of=day1
    )
    assert changed == 1

    rows = db_session.query(MacroDataPoint).filter_by(indicator_code="TEST_SNAPSHOT_RATE").all()
    assert len(rows) == 1
    assert rows[0].release_date == day1
    assert rows[0].revision_date == day1
    assert rows[0].original_value == pytest.approx(4.35)
    assert rows[0].revised_value is None

    # Second ingest, later day, same value -> no change, no new row.
    provider = _FakeSnapshotProvider([_snapshot_record(period, 4.35)])
    changed = ingest_snapshot_macro_data(
        db_session, provider, countries=["AU"], start=period, end=period, as_of=day2
    )
    assert changed == 0
    rows = db_session.query(MacroDataPoint).filter_by(indicator_code="TEST_SNAPSHOT_RATE").all()
    assert len(rows) == 1

    # Third ingest, later day, value actually changed -> new revision row, original
    # release_date preserved from the first time we saw this period.
    provider = _FakeSnapshotProvider([_snapshot_record(period, 4.60)])
    changed = ingest_snapshot_macro_data(
        db_session, provider, countries=["AU"], start=period, end=period, as_of=day3
    )
    assert changed == 1
    rows = db_session.query(MacroDataPoint).filter_by(indicator_code="TEST_SNAPSHOT_RATE").all()
    assert len(rows) == 2
    latest = max(rows, key=lambda r: r.revision_date)
    assert latest.value == pytest.approx(4.60)
    assert latest.revised_value == pytest.approx(4.60)
    assert latest.release_date == day1  # preserved, not reset to day3
    assert latest.revision_date == day3

    # Fourth ingest, *same* day3 but a different value again (e.g. re-run same day) ->
    # updates the day3 row in place rather than creating a second same-day vintage.
    provider = _FakeSnapshotProvider([_snapshot_record(period, 4.75)])
    changed = ingest_snapshot_macro_data(
        db_session, provider, countries=["AU"], start=period, end=period, as_of=day3
    )
    assert changed == 1
    rows = db_session.query(MacroDataPoint).filter_by(indicator_code="TEST_SNAPSHOT_RATE").all()
    assert len(rows) == 2  # still two rows, not three
    latest = max(rows, key=lambda r: r.revision_date)
    assert latest.value == pytest.approx(4.75)
    assert latest.release_date == day1
