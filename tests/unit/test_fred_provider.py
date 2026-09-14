from __future__ import annotations

import datetime as dt

import httpx
import pytest

from jlmacro.data.macro.fred import FredProvider


def _client_returning(payload: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fred_provider_parses_alfred_vintages():
    # Shape matches FRED's real /fred/series/observations response when queried with
    # realtime_start=1776-07-04&realtime_end=9999-12-31 (full vintage history): the
    # January observation has two vintages (an original and a later revision), the
    # February observation has only its first vintage so far.
    payload = {
        "observations": [
            {
                "realtime_start": "2024-02-14",
                "realtime_end": "2024-03-13",
                "date": "2024-01-01",
                "value": "3.1",
            },
            {
                "realtime_start": "2024-03-14",
                "realtime_end": "9999-12-31",
                "date": "2024-01-01",
                "value": "3.2",
            },
            {
                "realtime_start": "2024-03-14",
                "realtime_end": "9999-12-31",
                "date": "2024-02-01",
                "value": "3.0",
            },
        ]
    }
    provider = FredProvider(api_key="TEST_KEY", client=_client_returning(payload))

    records = provider.fetch(
        identifiers=["CPI_HEADLINE"],
        start=dt.date(2024, 1, 1),
        end=dt.date(2024, 3, 1),
        countries=["US"],
    )

    assert len(records) == 3
    jan_records = sorted(
        (r for r in records if r["effective_date"] == dt.date(2024, 1, 1)),
        key=lambda r: r["revision_date"],
    )
    first, revision = jan_records

    assert first["value"] == pytest.approx(3.1)
    assert first["original_value"] == pytest.approx(3.1)
    assert first["revised_value"] is None
    assert first["release_date"] == dt.date(2024, 2, 14)
    assert first["revision_date"] == dt.date(2024, 2, 14)
    assert first["country"] == "US"
    assert first["source"] == "FRED"

    # release_date stays the *first* vintage's date even on the revision row - it must
    # never move to match revision_date, or PIT queries filtering on release_date would
    # incorrectly treat the revision as "known" from the very first release.
    assert revision["release_date"] == dt.date(2024, 2, 14)
    assert revision["revision_date"] == dt.date(2024, 3, 14)
    assert revision["value"] == pytest.approx(3.2)
    assert revision["original_value"] == pytest.approx(3.1)
    assert revision["revised_value"] == pytest.approx(3.2)

    feb_record = next(r for r in records if r["effective_date"] == dt.date(2024, 2, 1))
    assert feb_record["revised_value"] is None


def test_fred_provider_skips_missing_value_marker():
    payload = {
        "observations": [
            {
                "realtime_start": "2024-02-14",
                "realtime_end": "9999-12-31",
                "date": "2024-01-01",
                "value": ".",
            },
        ]
    }
    provider = FredProvider(api_key="TEST_KEY", client=_client_returning(payload))
    records = provider.fetch(
        identifiers=["CPI_HEADLINE"],
        start=dt.date(2024, 1, 1),
        end=dt.date(2024, 2, 1),
        countries=["US"],
    )
    assert records == []


def test_fred_provider_skips_unmapped_indicator_without_http_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"observations": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FredProvider(api_key="TEST_KEY", client=client)

    records = provider.fetch(
        identifiers=["NOT_A_KNOWN_INDICATOR"],
        start=dt.date(2024, 1, 1),
        end=dt.date(2024, 2, 1),
        countries=["US"],
    )
    assert records == []
    assert calls == []  # No FRED series mapped -> no HTTP call made at all.


def test_fred_provider_requires_api_key():
    provider = FredProvider(api_key=None, client=_client_returning({"observations": []}))
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        provider.fetch(
            identifiers=["CPI_HEADLINE"],
            start=dt.date(2024, 1, 1),
            end=dt.date(2024, 2, 1),
            countries=["US"],
        )
