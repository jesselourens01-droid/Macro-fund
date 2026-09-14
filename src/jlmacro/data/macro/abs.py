"""Australian Bureau of Statistics (ABS) adapter.

Uses the ABS Data API, which follows the standard SDMX-JSON format (the same shape
used by Eurostat, OECD, INSEE, etc.): a "dataSets[0].series" map keyed by a
dimension-index string, each holding an "observations" map from observation-index to
[value, ...attributes], plus a "structure.dimensions.observation" array (matching the
TIME_PERIOD dimension) that gives the period label for each observation index. No API
key is required.

Like RBAProvider, the ABS Data API's basic query used here only returns *current*
values, not a vintage history, so release_date/revision_date are left None here -
jlmacro.data.loader's snapshot ingestion path fills them in relative to when the data
was actually fetched. The specific dataflow/key identifiers in
config/macro_indicators.yaml's provider_series_ids.ABS section should be verified
against the live API - see the comment there.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from typing import Any, Self

import httpx

from jlmacro.data.base import BaseMacroDataProvider
from jlmacro.data.http import build_http_client
from jlmacro.data.indicator_metadata import category_for, frequency_for, provider_series_map

_BASE_URL = "https://data.api.abs.gov.au/rest/data"

_YEAR_RE = re.compile(r"^\d{4}$")
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _parse_period(period: str) -> dt.date | None:
    """Convert an SDMX TIME_PERIOD label to a period-end date, matching the
    effective_date convention used elsewhere in the platform (e.g. the synthetic
    macro provider).
    """
    period = period.strip()
    if _YEAR_RE.match(period):
        return dt.date(int(period), 12, 31)
    if match := _QUARTER_RE.match(period):
        year, quarter = int(match.group(1)), int(match.group(2))
        month = quarter * 3
        return dt.date(year, month, calendar.monthrange(year, month)[1])
    if match := _MONTH_RE.match(period):
        year, month = int(match.group(1)), int(match.group(2))
        return dt.date(year, month, calendar.monthrange(year, month)[1])
    if match := _DAY_RE.match(period):
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


class ABSProvider(BaseMacroDataProvider):
    name = "ABS"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
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
        countries = countries or ["AU"]
        series_map = provider_series_map("ABS")

        records: list[dict[str, Any]] = []
        for country in countries:
            country_series = series_map.get(country, {})
            for indicator_code in identifiers:
                mapping = country_series.get(indicator_code)
                if not mapping:
                    continue  # No known ABS dataflow/key for this country/indicator.
                records.extend(self._fetch_series(country, indicator_code, mapping, start, end))
        return records

    def _fetch_series(
        self,
        country: str,
        indicator_code: str,
        mapping: dict[str, Any],
        start: dt.date,
        end: dt.date,
    ) -> list[dict[str, Any]]:
        dataflow = mapping["dataflow"]
        key = mapping["key"]
        url = f"{_BASE_URL}/{dataflow}/{key}"
        params = {
            "startPeriod": start.isoformat(),
            "endPeriod": end.isoformat(),
            "format": "jsondata",
        }
        response = self._client.get(url, params=params)
        response.raise_for_status()
        return self._parse_sdmx_json(response.json(), country, indicator_code, start, end)

    @staticmethod
    def _parse_sdmx_json(
        payload: dict[str, Any], country: str, indicator_code: str, start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        data = payload.get("data", payload)
        datasets = data.get("dataSets", [])
        observation_dims = data.get("structure", {}).get("dimensions", {}).get("observation", [])
        time_dim = next((d for d in observation_dims if d.get("id") == "TIME_PERIOD"), None)
        if time_dim is None or not datasets:
            return []
        period_values = time_dim.get("values", [])

        category = category_for(indicator_code)
        frequency = frequency_for(indicator_code)

        records: list[dict[str, Any]] = []
        for series in datasets[0].get("series", {}).values():
            for obs_index_str, obs_value in series.get("observations", {}).items():
                obs_index = int(obs_index_str)
                if obs_index >= len(period_values) or not obs_value:
                    continue
                effective_date = _parse_period(period_values[obs_index]["id"])
                if effective_date is None or not (start <= effective_date <= end):
                    continue
                value = obs_value[0]
                if value is None:
                    continue

                records.append(
                    {
                        "country": country,
                        "indicator_code": indicator_code,
                        "category": category,
                        "frequency": frequency,
                        "effective_date": effective_date,
                        "release_date": None,
                        "revision_date": None,
                        "value": float(value),
                        "original_value": None,
                        "revised_value": None,
                        "source": "ABS",
                    }
                )
        return records
