from __future__ import annotations

import datetime as dt

import httpx
import pytest

from jlmacro.data.macro.rba import RBAProvider

# Matches the real, long-stable RBA statistical-table CSV layout: a block of metadata
# rows, then a "Series ID" row whose columns are the series codes, then dated rows.
_SAMPLE_TABLE_CSV = """Title,Interest rates and yields - money market - F1
Description,Cash rate target and other money market rates
Frequency,Daily
Type,Original
Units,Per cent per annum
Source,RBA
Publication date,15-Jan-2024
Series ID,FIRMMCRTD,FOOBAR
1-Jan-2024,4.35,1.23
2-Jan-2024,4.35,1.24
3-Jan-2024,4.60,1.30
"""


def _client_returning_csv(csv_text: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv_text)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_rba_provider_parses_table():
    provider = RBAProvider(client=_client_returning_csv(_SAMPLE_TABLE_CSV))

    records = provider.fetch(
        identifiers=["POLICY_RATE"],
        start=dt.date(2024, 1, 1),
        end=dt.date(2024, 1, 3),
        countries=["AU"],
    )

    assert len(records) == 3
    by_date = {r["effective_date"]: r for r in records}
    assert by_date[dt.date(2024, 1, 1)]["value"] == pytest.approx(4.35)
    assert by_date[dt.date(2024, 1, 3)]["value"] == pytest.approx(4.60)

    rec = by_date[dt.date(2024, 1, 1)]
    assert rec["country"] == "AU"
    assert rec["source"] == "RBA"
    # RBA's CSV tables expose only the current value, never a vintage history - the
    # provider must not fabricate release_date/revision_date; the loader's snapshot
    # ingestion path is responsible for stamping those at actual ingestion time.
    assert rec["release_date"] is None
    assert rec["revision_date"] is None
    assert rec["original_value"] is None
    assert rec["revised_value"] is None


def test_rba_provider_filters_by_date_range():
    provider = RBAProvider(client=_client_returning_csv(_SAMPLE_TABLE_CSV))
    records = provider.fetch(
        identifiers=["POLICY_RATE"],
        start=dt.date(2024, 1, 2),
        end=dt.date(2024, 1, 2),
        countries=["AU"],
    )
    assert len(records) == 1
    assert records[0]["effective_date"] == dt.date(2024, 1, 2)


def test_rba_provider_skips_unmapped_indicator_without_http_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text=_SAMPLE_TABLE_CSV)

    provider = RBAProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    records = provider.fetch(
        identifiers=["NOT_A_KNOWN_INDICATOR"],
        start=dt.date(2024, 1, 1),
        end=dt.date(2024, 1, 3),
        countries=["AU"],
    )
    assert records == []
    assert calls == []


def test_rba_provider_raises_on_missing_series_id():
    bad_csv = _SAMPLE_TABLE_CSV.replace("FIRMMCRTD", "SOME_OTHER_SERIES")
    provider = RBAProvider(client=_client_returning_csv(bad_csv))
    with pytest.raises(ValueError, match="not found"):
        provider.fetch(
            identifiers=["POLICY_RATE"],
            start=dt.date(2024, 1, 1),
            end=dt.date(2024, 1, 3),
            countries=["AU"],
        )


def test_rba_provider_raises_when_header_row_missing():
    provider = RBAProvider(client=_client_returning_csv("Title,No series here\n1-Jan-2024,4.35\n"))
    with pytest.raises(ValueError, match="Series ID"):
        provider.fetch(
            identifiers=["POLICY_RATE"],
            start=dt.date(2024, 1, 1),
            end=dt.date(2024, 1, 3),
            countries=["AU"],
        )
