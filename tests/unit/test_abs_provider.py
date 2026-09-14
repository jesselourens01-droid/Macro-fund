from __future__ import annotations

import datetime as dt

import httpx
import pytest

from jlmacro.data.macro.abs import ABSProvider, _parse_period

# Shape matches the standard SDMX-JSON format the ABS Data API uses (the same general
# shape as Eurostat/OECD/INSEE): dataSets[0].series[<dim-key>].observations maps an
# observation index to [value, ...attributes], and structure.dimensions.observation
# gives the TIME_PERIOD label for each index.
_SAMPLE_SDMX_JSON = {
    "data": {
        "dataSets": [
            {
                "series": {
                    "0:0:0:0:0": {
                        "observations": {
                            "0": [130.1, 0],
                            "1": [131.4, 0],
                        }
                    }
                }
            }
        ],
        "structure": {
            "dimensions": {
                "observation": [
                    {
                        "id": "TIME_PERIOD",
                        "values": [
                            {"id": "2023-Q4", "name": "Dec 2023"},
                            {"id": "2024-Q1", "name": "Mar 2024"},
                        ],
                    }
                ]
            }
        },
    }
}


def _client_returning(payload: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "period,expected",
    [
        ("2023", dt.date(2023, 12, 31)),
        ("2023-Q4", dt.date(2023, 12, 31)),
        ("2024-Q1", dt.date(2024, 3, 31)),
        ("2024-02", dt.date(2024, 2, 29)),
        ("2024-02-15", dt.date(2024, 2, 15)),
        ("not-a-period", None),
    ],
)
def test_parse_period(period, expected):
    assert _parse_period(period) == expected


def test_abs_provider_parses_sdmx_json():
    provider = ABSProvider(client=_client_returning(_SAMPLE_SDMX_JSON))

    records = provider.fetch(
        identifiers=["CPI_HEADLINE"],
        start=dt.date(2023, 1, 1),
        end=dt.date(2024, 12, 31),
        countries=["AU"],
    )

    assert len(records) == 2
    by_date = {r["effective_date"]: r for r in records}
    assert by_date[dt.date(2023, 12, 31)]["value"] == pytest.approx(130.1)
    assert by_date[dt.date(2024, 3, 31)]["value"] == pytest.approx(131.4)

    rec = by_date[dt.date(2023, 12, 31)]
    assert rec["country"] == "AU"
    assert rec["source"] == "ABS"
    assert rec["release_date"] is None
    assert rec["revision_date"] is None


def test_abs_provider_builds_url_from_verified_worked_example():
    # Locks in that CPI_HEADLINE's config/macro_indicators.yaml mapping still matches
    # the worked example straight from ABS's own Data API documentation:
    # https://data.api.abs.gov.au/rest/data/ABS,CPI,2.0.0/1.10001.10.50.M
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_SAMPLE_SDMX_JSON)

    provider = ABSProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider.fetch(
        identifiers=["CPI_HEADLINE"],
        start=dt.date(2023, 1, 1),
        end=dt.date(2024, 12, 31),
        countries=["AU"],
    )

    assert len(captured) == 1
    assert captured[0].url.path == "/rest/data/ABS,CPI,2.0.0/1.10001.10.50.M"


def test_abs_provider_filters_by_date_range():
    provider = ABSProvider(client=_client_returning(_SAMPLE_SDMX_JSON))
    records = provider.fetch(
        identifiers=["CPI_HEADLINE"],
        start=dt.date(2024, 1, 1),
        end=dt.date(2024, 12, 31),
        countries=["AU"],
    )
    assert len(records) == 1
    assert records[0]["effective_date"] == dt.date(2024, 3, 31)


def test_abs_provider_skips_unmapped_indicator_without_http_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_SAMPLE_SDMX_JSON)

    provider = ABSProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    records = provider.fetch(
        identifiers=["NOT_A_KNOWN_INDICATOR"],
        start=dt.date(2023, 1, 1),
        end=dt.date(2024, 12, 31),
        countries=["AU"],
    )
    assert records == []
    assert calls == []
