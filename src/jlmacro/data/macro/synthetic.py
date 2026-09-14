"""Synthetic macroeconomic data provider.

Generates deterministic, mean-reverting monthly indicator series per (country, indicator)
plus a first-release row and, for roughly a third of periods, a subsequent revision row -
so the point-in-time model (release_date vs revision_date vs effective_date) has
something realistic to exercise even before Phase 2's real adapters exist.
"""

from __future__ import annotations

import calendar
import datetime as dt
import zlib
from typing import Any

import numpy as np

from jlmacro.data.base import BaseMacroDataProvider

# (typical level, typical stdev) per indicator code - deliberately rough, just enough to
# make series look plausible rather than to model any real economy.
_INDICATOR_PARAMS: dict[str, tuple[float, float]] = {
    "PMI_MFG": (50.0, 3.0),
    "PMI_SERVICES": (52.0, 3.0),
    "INDUSTRIAL_PRODUCTION": (1.0, 2.0),
    "RETAIL_SALES": (2.0, 1.5),
    "GDP": (2.0, 1.2),
    "CONSUMER_CONFIDENCE": (100.0, 8.0),
    "EMPLOYMENT": (0.2, 0.3),
    "CPI_HEADLINE": (3.0, 1.0),
    "CPI_CORE": (3.0, 0.8),
    "PCE": (2.8, 0.7),
    "WAGE_GROWTH": (3.5, 0.6),
    "PPI": (2.0, 1.5),
    "BREAKEVEN_INFLATION": (2.3, 0.3),
    "POLICY_RATE": (4.0, 0.5),
    "YIELD_CURVE_SLOPE": (0.3, 0.5),
    "RATE_EXPECTATIONS": (4.0, 0.5),
    "CREDIT_SPREAD_IG": (120.0, 20.0),
    "CREDIT_SPREAD_HY": (400.0, 60.0),
    "EQUITY_VOL": (16.0, 5.0),
    "BOND_VOL": (90.0, 20.0),
    "MONEY_SUPPLY": (4.0, 2.0),
}

_INDICATOR_CATEGORY: dict[str, str] = {
    "PMI_MFG": "growth",
    "PMI_SERVICES": "growth",
    "INDUSTRIAL_PRODUCTION": "growth",
    "RETAIL_SALES": "growth",
    "GDP": "growth",
    "CONSUMER_CONFIDENCE": "growth",
    "EMPLOYMENT": "growth",
    "CPI_HEADLINE": "inflation",
    "CPI_CORE": "inflation",
    "PCE": "inflation",
    "WAGE_GROWTH": "inflation",
    "PPI": "inflation",
    "BREAKEVEN_INFLATION": "inflation",
    "POLICY_RATE": "monetary_policy",
    "YIELD_CURVE_SLOPE": "monetary_policy",
    "RATE_EXPECTATIONS": "monetary_policy",
    "CREDIT_SPREAD_IG": "financial_conditions",
    "CREDIT_SPREAD_HY": "financial_conditions",
    "EQUITY_VOL": "financial_conditions",
    "BOND_VOL": "financial_conditions",
    "MONEY_SUPPLY": "financial_conditions",
}

_INDICATOR_FREQUENCY: dict[str, str] = {
    "GDP": "quarterly",
    "WAGE_GROWTH": "quarterly",
}


def _seed(country: str, indicator: str) -> int:
    return zlib.crc32(f"{country}:{indicator}".encode()) % (2**32)


def _month_range(start: dt.date, end: dt.date) -> list[dt.date]:
    months = []
    cur = dt.date(start.year, start.month, 1)
    while cur <= end:
        last_day = calendar.monthrange(cur.year, cur.month)[1]
        months.append(dt.date(cur.year, cur.month, last_day))
        if cur.month == 12:
            cur = dt.date(cur.year + 1, 1, 1)
        else:
            cur = dt.date(cur.year, cur.month + 1, 1)
    return months


class SyntheticMacroDataProvider(BaseMacroDataProvider):
    name = "SYNTHETIC"

    def fetch(
        self,
        *,
        identifiers: list[str],
        start: dt.date,
        end: dt.date,
        countries: list[str] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        countries = countries or ["US"]
        records: list[dict[str, Any]] = []
        for country in countries:
            for indicator_code in identifiers:
                records.extend(self._generate_series(country, indicator_code, start, end))
        return records

    @staticmethod
    def _generate_series(
        country: str, indicator_code: str, start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        level, stdev = _INDICATOR_PARAMS.get(indicator_code, (0.0, 1.0))
        category = _INDICATOR_CATEGORY.get(indicator_code, "growth")
        frequency = _INDICATOR_FREQUENCY.get(indicator_code, "monthly")

        rng = np.random.default_rng(_seed(country, indicator_code))
        periods = _month_range(start, end)
        if frequency == "quarterly":
            periods = periods[2::3]

        records: list[dict[str, Any]] = []
        value = level
        for effective_date in periods:
            value = value + 0.3 * (level - value) + rng.normal(0.0, stdev * 0.3)
            original_value = round(float(value), 3)
            release_date = effective_date + dt.timedelta(days=14)

            records.append(
                {
                    "country": country,
                    "indicator_code": indicator_code,
                    "category": category,
                    "frequency": frequency,
                    "effective_date": effective_date,
                    "release_date": release_date,
                    "revision_date": release_date,
                    "value": original_value,
                    "original_value": original_value,
                    "revised_value": None,
                    "source": "SYNTHETIC",
                }
            )

            if rng.uniform() < 0.35:
                revised_value = round(original_value + rng.normal(0.0, stdev * 0.1), 3)
                revision_date = release_date + dt.timedelta(days=30)
                records.append(
                    {
                        "country": country,
                        "indicator_code": indicator_code,
                        "category": category,
                        "frequency": frequency,
                        "effective_date": effective_date,
                        "release_date": release_date,
                        "revision_date": revision_date,
                        "value": revised_value,
                        "original_value": original_value,
                        "revised_value": revised_value,
                        "source": "SYNTHETIC",
                    }
                )
        return records
