from __future__ import annotations

import datetime as dt

from jlmacro.data.quality import validate_macro_records, validate_market_records


def _bar(symbol: str, day: int, close: float, **overrides) -> dict:
    rec = {
        "symbol": symbol,
        "timestamp": dt.datetime(2024, 1, day, tzinfo=dt.UTC),
        "effective_date": dt.date(2024, 1, day),
        "frequency": "daily",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000.0,
        "source": "TEST",
    }
    rec.update(overrides)
    return rec


def test_validate_market_records_detects_duplicate_timestamp():
    records = [_bar("X", 1, 100.0), _bar("X", 1, 101.0)]
    report = validate_market_records(records)
    assert any(i.check == "duplicate_timestamp" for i in report.issues)
    assert report.has_errors


def test_validate_market_records_detects_impossible_values():
    records = [_bar("X", 1, -5.0)]
    report = validate_market_records(records)
    assert any(i.check == "impossible_value" for i in report.issues)
    assert report.has_errors


def test_validate_market_records_detects_high_low_inversion():
    records = [_bar("X", 1, 100.0, high=90.0, low=95.0)]
    report = validate_market_records(records)
    assert any("high < low" in i.message for i in report.issues)


def test_validate_market_records_detects_stale_price():
    records = [_bar("X", d, 100.0) for d in range(1, 8)]
    report = validate_market_records(records)
    assert any(i.check == "stale_price" for i in report.issues)
    assert not report.has_errors  # stale is a warning, not an error


def test_validate_market_records_detects_missing_observation_gap():
    records = [_bar("X", 1, 100.0), _bar("X", 20, 101.0)]
    for rec in records:
        rec["frequency"] = "daily"
    report = validate_market_records(records)
    assert any(i.check == "missing_observation" for i in report.issues)


def test_validate_market_records_clean_data_has_no_issues():
    records = [_bar("X", d, 100.0 + d * 0.1) for d in range(1, 6)]
    report = validate_market_records(records)
    assert not report
    assert not report.has_errors


def _macro(country, indicator, effective_date, value, **overrides) -> dict:
    rec = {
        "country": country,
        "indicator_code": indicator,
        "category": "inflation",
        "frequency": "monthly",
        "effective_date": effective_date,
        "release_date": effective_date,
        "revision_date": effective_date,
        "value": value,
        "original_value": value,
        "revised_value": None,
        "source": "TEST",
    }
    rec.update(overrides)
    return rec


def test_validate_macro_records_detects_duplicate_vintage():
    day = dt.date(2024, 1, 31)
    records = [_macro("US", "CPI_HEADLINE", day, 3.0), _macro("US", "CPI_HEADLINE", day, 3.5)]
    report = validate_macro_records(records)
    assert any(i.check == "duplicate_timestamp" for i in report.issues)
    assert report.has_errors


def test_validate_macro_records_detects_revision_before_release():
    rec = _macro(
        "US",
        "CPI_HEADLINE",
        dt.date(2024, 1, 31),
        3.0,
        release_date=dt.date(2024, 2, 14),
        revision_date=dt.date(2024, 1, 1),
    )
    report = validate_macro_records([rec])
    assert any(i.check == "revision_mismatch" and i.severity == "error" for i in report.issues)
    assert report.has_errors


def test_validate_macro_records_detects_revised_without_original():
    rec = _macro(
        "US", "CPI_HEADLINE", dt.date(2024, 1, 31), 3.0, original_value=None, revised_value=3.2
    )
    report = validate_macro_records([rec])
    assert any(i.check == "revision_mismatch" and i.severity == "warning" for i in report.issues)
    assert not report.has_errors


def test_validate_macro_records_detects_missing_value():
    rec = _macro("US", "CPI_HEADLINE", dt.date(2024, 1, 31), 3.0)
    rec["value"] = None
    report = validate_macro_records([rec])
    assert any(i.check == "impossible_value" for i in report.issues)
    assert report.has_errors


def test_validate_macro_records_detects_missing_observation_gap():
    records = [
        _macro("US", "CPI_HEADLINE", dt.date(2024, 1, 31), 3.0),
        _macro("US", "CPI_HEADLINE", dt.date(2024, 6, 30), 3.1),
    ]
    report = validate_macro_records(records)
    assert any(i.check == "missing_observation" for i in report.issues)


def test_validate_macro_records_clean_data_has_no_issues():
    records = [
        _macro(
            "US",
            "CPI_HEADLINE",
            dt.date(2024, 1, 31),
            3.0,
            release_date=dt.date(2024, 2, 14),
            revision_date=dt.date(2024, 2, 14),
        ),
        _macro(
            "US",
            "CPI_HEADLINE",
            dt.date(2024, 2, 29),
            3.1,
            release_date=dt.date(2024, 3, 14),
            revision_date=dt.date(2024, 3, 14),
        ),
    ]
    report = validate_macro_records(records)
    assert not report.has_errors
