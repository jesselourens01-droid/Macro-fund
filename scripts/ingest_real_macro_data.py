#!/usr/bin/env python
"""Ingest real macro data from FRED, RBA or ABS (Phase 2 adapters).

Unlike scripts/generate_synthetic_data.py, this makes real outbound HTTP calls and
(for FRED) requires an API key. See README.md's "Real data adapters" section.

Usage:
    python scripts/ingest_real_macro_data.py --source fred --countries US
    python scripts/ingest_real_macro_data.py --source rba --countries AU
    python scripts/ingest_real_macro_data.py --source abs --countries AU
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jlmacro.data.loader import (
    ingest_abs_macro_data,
    ingest_fred_macro_data,
    ingest_rba_macro_data,
)
from jlmacro.database.session import session_scope
from jlmacro.utils.audit import log_event
from jlmacro.utils.logging import configure_logging, get_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    today = dt.datetime.now(tz=dt.UTC).date()
    parser.add_argument("--source", required=True, choices=["fred", "rba", "abs"])
    parser.add_argument(
        "--countries", default="", help="Comma-separated country codes, e.g. US or AU"
    )
    parser.add_argument(
        "--start", type=dt.date.fromisoformat, default=today - dt.timedelta(days=365 * 10)
    )
    parser.add_argument("--end", type=dt.date.fromisoformat, default=today)
    return parser.parse_args()


def main() -> None:
    configure_logging()
    log = get_logger(__name__)
    args = parse_args()

    default_countries = {"fred": ["US"], "rba": ["AU"], "abs": ["AU"]}[args.source]
    countries = [
        c.strip().upper() for c in args.countries.split(",") if c.strip()
    ] or default_countries

    with session_scope() as session:
        if args.source == "fred":
            rows = ingest_fred_macro_data(
                session, countries=countries, start=args.start, end=args.end
            )
        elif args.source == "rba":
            rows = ingest_rba_macro_data(
                session, countries=countries, start=args.start, end=args.end
            )
        else:
            rows = ingest_abs_macro_data(
                session, countries=countries, start=args.start, end=args.end
            )

        log_event(
            session,
            event_type="real_macro_data_ingested",
            entity_type="database",
            entity_id=args.source,
            payload={
                "source": args.source,
                "countries": countries,
                "rows": rows,
                "start": str(args.start),
                "end": str(args.end),
            },
            actor="scripts/ingest_real_macro_data.py",
        )

    log.info("real_macro_data_ingest_complete", source=args.source, countries=countries, rows=rows)


if __name__ == "__main__":
    main()
