"""Reserve Bank of Australia (RBA) adapter.

Parses RBA's published statistical-table CSV format: a block of metadata rows
(Title/Description/Frequency/Type/Units/Source/Publication date), then a "Series ID"
row whose columns are the series codes, then dated data rows. This layout has been
stable on rba.gov.au for a long time, but the exact table/series codes referenced in
config/macro_indicators.yaml's provider_series_ids.RBA section should be verified
against the live site - see the comment there.

Unlike FredProvider (which gets true historical vintages from FRED's ALFRED API), RBA's
CSV tables only expose the *current* known value for each period - there is no public
RBA vintage/revision history feed. So records from this provider always carry
release_date=None, revision_date=None: the caller (jlmacro.data.loader's snapshot
ingestion path) is responsible for treating the moment of ingestion as the knowledge
date and only creating a new MacroDataPoint row when a value has actually changed
since the last time it was fetched.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any, Self

import httpx

from jlmacro.data.base import BaseMacroDataProvider
from jlmacro.data.http import build_http_client
from jlmacro.data.indicator_metadata import category_for, frequency_for, provider_series_map

_DATE_FORMATS = ("%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y")


def _parse_rba_date(raw: str) -> dt.date | None:
    for fmt in _DATE_FORMATS:
        try:
            # These date-only labels carry no timezone; strptime's naive result is
            # immediately reduced to a plain date(), so there is no aware/naive risk.
            return dt.datetime.strptime(raw, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None


class RBAProvider(BaseMacroDataProvider):
    name = "RBA"

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
        series_map = provider_series_map("RBA")
        csv_cache: dict[str, str] = {}

        records: list[dict[str, Any]] = []
        for country in countries:
            country_series = series_map.get(country, {})
            for indicator_code in identifiers:
                mapping = country_series.get(indicator_code)
                if not mapping:
                    continue  # No known RBA table/series for this country/indicator.

                csv_url = str(mapping["csv_url"])
                series_id = str(mapping["series_id"])
                if csv_url not in csv_cache:
                    response = self._client.get(csv_url)
                    response.raise_for_status()
                    csv_cache[csv_url] = response.text

                records.extend(
                    self._parse_table(
                        csv_cache[csv_url], country, indicator_code, series_id, start, end
                    )
                )
        return records

    @staticmethod
    def _parse_table(
        csv_text: str,
        country: str,
        indicator_code: str,
        series_id: str,
        start: dt.date,
        end: dt.date,
    ) -> list[dict[str, Any]]:
        rows = list(csv.reader(io.StringIO(csv_text)))

        header_idx = next(
            (i for i, row in enumerate(rows) if row and row[0].strip().lower() == "series id"),
            None,
        )
        if header_idx is None:
            raise ValueError("Could not find the 'Series ID' header row in the RBA CSV table")

        header = rows[header_idx]
        try:
            col_idx = header.index(series_id)
        except ValueError as exc:
            raise ValueError(
                f"Series ID {series_id!r} not found in RBA table columns: {header[1:]}"
            ) from exc

        category = category_for(indicator_code)
        frequency = frequency_for(indicator_code)

        records: list[dict[str, Any]] = []
        for row in rows[header_idx + 1 :]:
            if not row or not row[0].strip():
                continue
            effective_date = _parse_rba_date(row[0].strip())
            if effective_date is None or not (start <= effective_date <= end):
                continue
            if col_idx >= len(row):
                continue
            raw_value = row[col_idx].strip()
            if not raw_value:
                continue
            try:
                value = float(raw_value)
            except ValueError:
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
                    "value": value,
                    "original_value": None,
                    "revised_value": None,
                    "source": "RBA",
                }
            )
        return records
