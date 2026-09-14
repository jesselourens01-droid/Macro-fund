#!/usr/bin/env python
"""Compute and persist macro regime snapshots for the configured countries.

Reads whatever MacroDataPoint history already exists (synthetic and/or real) and
writes one RegimeSnapshot per (country, as_of) - safe to re-run; existing snapshots
are updated in place rather than duplicated.

Usage:
    python scripts/compute_regime_snapshots.py
    python scripts/compute_regime_snapshots.py --countries US,AU --start 2023-01-01 --end 2026-09-01
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jlmacro.config import load_yaml_config
from jlmacro.database.session import session_scope
from jlmacro.models.regime import compute_and_persist_snapshot
from jlmacro.utils.audit import log_event
from jlmacro.utils.logging import configure_logging, get_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    today = dt.datetime.now(tz=dt.UTC).date()
    parser.add_argument(
        "--countries", default="", help="Comma-separated country codes; default: all configured"
    )
    parser.add_argument(
        "--start", type=dt.date.fromisoformat, default=today - dt.timedelta(days=365 * 3)
    )
    parser.add_argument("--end", type=dt.date.fromisoformat, default=today)
    return parser.parse_args()


def _month_end_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    dates = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        last_day = calendar.monthrange(year, month)[1]
        month_end = dt.date(year, month, last_day)
        if start <= month_end <= end:
            dates.append(month_end)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return dates


def main() -> None:
    configure_logging()
    log = get_logger(__name__)
    args = parse_args()

    countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    if not countries:
        countries = load_yaml_config("macro_indicators").get("countries", [])

    as_of_dates = _month_end_dates(args.start, args.end)
    total = 0

    with session_scope() as session:
        for country in countries:
            for as_of in as_of_dates:
                compute_and_persist_snapshot(session, country, as_of=as_of)
                total += 1
            log.info("regime_snapshots_computed", country=country, periods=len(as_of_dates))

        log_event(
            session,
            event_type="regime_snapshots_computed",
            entity_type="database",
            entity_id="regime",
            payload={
                "countries": countries,
                "periods": len(as_of_dates),
                "start": str(args.start),
                "end": str(args.end),
            },
            actor="scripts/compute_regime_snapshots.py",
        )

    log.info("regime_snapshot_compute_complete", countries=countries, snapshots=total)


if __name__ == "__main__":
    main()
