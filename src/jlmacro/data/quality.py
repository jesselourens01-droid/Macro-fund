"""Data-quality validation for provider output, run before it is persisted.

Applies to both real adapters (Fred/RBA/ABS) and the synthetic providers alike -
anything shaped like the standardised MarketDataPoint/MacroDataPoint record dicts that
jlmacro.data.base.BaseDataProvider implementations return. Detects the issue classes
called out in the platform spec: missing observations, duplicate timestamps, stale
prices, impossible values, outliers, revision mismatches.

This module flags issues; it does not decide what to do about them. Callers (the
loader/ingestion scripts) choose whether to log, alert, drop, or still insert.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

_FREQUENCY_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 31,
    "quarterly": 92,
}


@dataclass
class DataQualityIssue:
    severity: str  # "warning" | "error"
    check: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataQualityReport:
    issues: list[DataQualityIssue] = field(default_factory=list)

    def add(self, severity: str, check: str, message: str, **context: Any) -> None:
        self.issues.append(DataQualityIssue(severity, check, message, context))

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def __len__(self) -> int:
        return len(self.issues)

    def __bool__(self) -> bool:
        return bool(self.issues)


def _zscore_outliers(values: list[float], threshold: float = 6.0) -> list[int]:
    """Return indices of values whose z-score (vs. the rest of the series) exceeds
    threshold. Uses a simple population z-score; fine for flagging gross data errors,
    not intended as a statistical outlier model.
    """
    if len(values) < 5:
        return []
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    stdev = math.sqrt(variance)
    if stdev == 0:
        return []
    return [i for i, v in enumerate(values) if abs((v - mean) / stdev) > threshold]


def validate_market_records(records: list[dict[str, Any]]) -> DataQualityReport:
    """Validate a batch of MarketDataPoint-shaped record dicts (as returned by
    BaseMarketDataProvider.fetch), grouped by symbol/instrument identifier.
    """
    report = DataQualityReport()
    by_symbol: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        key = rec.get("symbol") or rec.get("instrument_id")
        by_symbol[key].append(rec)

    for symbol, group in by_symbol.items():
        group = sorted(group, key=lambda r: r["timestamp"])

        seen_timestamps: set[Any] = set()
        stale_run = 1
        closes = [r["close"] for r in group]
        outlier_idx = set()
        if len(closes) > 1:
            log_returns = [
                math.log(closes[i] / closes[i - 1])
                for i in range(1, len(closes))
                if closes[i - 1] > 0 and closes[i] > 0
            ]
            outlier_idx = set(_zscore_outliers(log_returns))

        for i, rec in enumerate(group):
            ts = rec["timestamp"]
            if ts in seen_timestamps:
                report.add(
                    "error",
                    "duplicate_timestamp",
                    f"{symbol}: duplicate timestamp {ts}",
                    symbol=symbol,
                    timestamp=str(ts),
                )
            seen_timestamps.add(ts)

            close, high, low, volume = (
                rec.get("close"),
                rec.get("high"),
                rec.get("low"),
                rec.get("volume"),
            )
            if close is None or close <= 0:
                report.add(
                    "error",
                    "impossible_value",
                    f"{symbol}: non-positive close {close} at {ts}",
                    symbol=symbol,
                    timestamp=str(ts),
                )
            if high is not None and low is not None and high < low:
                report.add(
                    "error",
                    "impossible_value",
                    f"{symbol}: high < low at {ts}",
                    symbol=symbol,
                    timestamp=str(ts),
                )
            if volume is not None and volume < 0:
                report.add(
                    "error",
                    "impossible_value",
                    f"{symbol}: negative volume at {ts}",
                    symbol=symbol,
                    timestamp=str(ts),
                )

            if i > 0 and group[i - 1].get("close") == close:
                stale_run += 1
                if stale_run >= 5:
                    report.add(
                        "warning",
                        "stale_price",
                        f"{symbol}: price unchanged for {stale_run} consecutive observations "
                        f"through {ts}",
                        symbol=symbol,
                        timestamp=str(ts),
                        run_length=stale_run,
                    )
            else:
                stale_run = 1

            if i > 0:
                gap = (rec["effective_date"] - group[i - 1]["effective_date"]).days
                frequency = rec.get("frequency", "daily")
                expected = _FREQUENCY_DAYS.get(frequency, 1)
                if gap > max(expected * 5, 7):
                    report.add(
                        "warning",
                        "missing_observation",
                        f"{symbol}: gap of {gap} days between observations ending {ts}",
                        symbol=symbol,
                        timestamp=str(ts),
                        gap_days=gap,
                    )

            if (i - 1) in outlier_idx:
                report.add(
                    "warning",
                    "outlier",
                    f"{symbol}: outlier return into {ts}",
                    symbol=symbol,
                    timestamp=str(ts),
                )

    return report


def validate_macro_records(records: list[dict[str, Any]]) -> DataQualityReport:
    """Validate a batch of MacroDataPoint-shaped record dicts (as returned by
    BaseMacroDataProvider.fetch), grouped by (country, indicator_code).
    """
    report = DataQualityReport()
    by_series: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        by_series[(rec["country"], rec["indicator_code"])].append(rec)

    for (country, indicator), group in by_series.items():
        group = sorted(
            group, key=lambda r: (r["effective_date"], r.get("revision_date") or dt.date.min)
        )

        seen_keys: set[tuple[Any, Any]] = set()
        values = [r["value"] for r in group if r.get("value") is not None]
        outlier_idx = set(_zscore_outliers(values))

        # Only compare consecutive *distinct* effective_date periods for the missing-
        # observation gap check, since a series can have multiple vintage rows sharing
        # one effective_date.
        distinct_periods = sorted({r["effective_date"] for r in group})

        for i, rec in enumerate(group):
            key = (rec["effective_date"], rec.get("revision_date"))
            if key in seen_keys:
                report.add(
                    "error",
                    "duplicate_timestamp",
                    f"{country}/{indicator}: duplicate vintage {key}",
                    country=country,
                    indicator=indicator,
                )
            seen_keys.add(key)

            value = rec.get("value")
            if value is None or (isinstance(value, float) and math.isnan(value)):
                report.add(
                    "error",
                    "impossible_value",
                    f"{country}/{indicator}: missing value at {rec['effective_date']}",
                    country=country,
                    indicator=indicator,
                )

            release_date, revision_date = rec.get("release_date"), rec.get("revision_date")
            if (
                release_date is not None
                and revision_date is not None
                and revision_date < release_date
            ):
                report.add(
                    "error",
                    "revision_mismatch",
                    f"{country}/{indicator}: revision_date {revision_date} precedes "
                    f"release_date {release_date}",
                    country=country,
                    indicator=indicator,
                )
            if rec.get("revised_value") is not None and rec.get("original_value") is None:
                report.add(
                    "warning",
                    "revision_mismatch",
                    f"{country}/{indicator}: revised_value set without an original_value",
                    country=country,
                    indicator=indicator,
                )

            if i in outlier_idx:
                report.add(
                    "warning",
                    "outlier",
                    f"{country}/{indicator}: outlier value {value} at {rec['effective_date']}",
                    country=country,
                    indicator=indicator,
                )

        frequency = group[0].get("frequency", "monthly") if group else "monthly"
        expected = _FREQUENCY_DAYS.get(frequency, 31)
        for i in range(1, len(distinct_periods)):
            gap = (distinct_periods[i] - distinct_periods[i - 1]).days
            if gap > expected * 1.5:
                report.add(
                    "warning",
                    "missing_observation",
                    f"{country}/{indicator}: gap of {gap} days between "
                    f"{distinct_periods[i - 1]} and {distinct_periods[i]}",
                    country=country,
                    indicator=indicator,
                    gap_days=gap,
                )

    return report
