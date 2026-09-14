"""FRED (Federal Reserve Economic Data) adapter.

Uses FRED's ALFRED vintage history (requesting the full realtime_start/realtime_end
range) rather than the plain "current values" endpoint, because ALFRED is one of the
few public sources that gives genuine point-in-time vintages for free: each
observation row already carries the exact date it became the current value, so we can
build correct release_date/revision_date rows directly from the API instead of having
to infer them locally (contrast with RBAProvider/ABSProvider, which only expose
current values and need diff-based revision detection - see jlmacro.data.loader).

Requires a free API key (FRED_API_KEY / Settings.fred_api_key):
https://fred.stlouisfed.org/docs/api/api_key.html
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Self

import httpx

from jlmacro.config import get_settings
from jlmacro.data.base import BaseMacroDataProvider
from jlmacro.data.http import build_http_client
from jlmacro.data.indicator_metadata import category_for, frequency_for, provider_series_map

_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_MISSING_VALUE_MARKER = "."


class FredProvider(BaseMacroDataProvider):
    name = "FRED"

    def __init__(self, *, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self._api_key = api_key or get_settings().fred_api_key
        self._client = client or build_http_client()
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch(
        self,
        *,
        identifiers: list[str],
        start: dt.date,
        end: dt.date,
        countries: list[str] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not self._api_key:
            raise RuntimeError(
                "FRED_API_KEY is not configured. Get a free key at "
                "https://fred.stlouisfed.org/docs/api/api_key.html and set it in .env."
            )

        countries = countries or ["US"]
        series_map = provider_series_map("FRED")

        records: list[dict[str, Any]] = []
        for country in countries:
            country_series = series_map.get(country, {})
            for indicator_code in identifiers:
                series_id = country_series.get(indicator_code)
                if series_id is None:
                    continue  # No known FRED series for this country/indicator - skip.
                records.extend(
                    self._fetch_series(country, indicator_code, str(series_id), start, end)
                )
        return records

    def _fetch_series(
        self, country: str, indicator_code: str, series_id: str, start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
            # Request the full vintage history rather than only the latest value.
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
        }
        response = self._client.get(_OBSERVATIONS_URL, params=params)
        response.raise_for_status()
        payload = response.json()

        by_effective_date: dict[dt.date, list[dict[str, str]]] = defaultdict(list)
        for obs in payload.get("observations", []):
            if obs["value"] == _MISSING_VALUE_MARKER:
                continue
            by_effective_date[dt.date.fromisoformat(obs["date"])].append(obs)

        category = category_for(indicator_code)
        frequency = frequency_for(indicator_code)

        records: list[dict[str, Any]] = []
        for effective_date, vintages in sorted(by_effective_date.items()):
            vintages.sort(key=lambda o: o["realtime_start"])
            original_value = float(vintages[0]["value"])
            release_date = dt.date.fromisoformat(vintages[0]["realtime_start"])

            for vintage in vintages:
                revision_date = dt.date.fromisoformat(vintage["realtime_start"])
                value = float(vintage["value"])
                records.append(
                    {
                        "country": country,
                        "indicator_code": indicator_code,
                        "category": category,
                        "frequency": frequency,
                        "effective_date": effective_date,
                        "release_date": release_date,
                        "revision_date": revision_date,
                        "value": value,
                        "original_value": original_value,
                        "revised_value": value if revision_date != release_date else None,
                        "source": "FRED",
                    }
                )
        return records
