#!/usr/bin/env python
"""Seed the database with the configured instrument universe and synthetic point-in-time
market/macro data, so the whole Phase 1 stack runs without any external API keys.

Usage:
    python scripts/generate_synthetic_data.py
    python scripts/generate_synthetic_data.py --start 2022-01-01 --end 2026-09-01
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jlmacro.data.loader import seed_instruments, seed_macro_data, seed_market_data
from jlmacro.database.session import session_scope
from jlmacro.utils.audit import log_event
from jlmacro.utils.logging import configure_logging, get_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    today = dt.datetime.now(tz=dt.UTC).date()
    parser.add_argument(
        "--start", type=dt.date.fromisoformat, default=today - dt.timedelta(days=365 * 3)
    )
    parser.add_argument("--end", type=dt.date.fromisoformat, default=today)
    return parser.parse_args()


def main() -> None:
    configure_logging()
    log = get_logger(__name__)
    args = parse_args()

    with session_scope() as session:
        instruments = seed_instruments(session)
        log.info("seeded_instruments", count=len(instruments))

        market_rows = seed_market_data(session, instruments, start=args.start, end=args.end)
        log.info("seeded_market_data", rows=market_rows, start=str(args.start), end=str(args.end))

        macro_rows = seed_macro_data(session, start=args.start, end=args.end)
        log.info("seeded_macro_data", rows=macro_rows, start=str(args.start), end=str(args.end))

        log_event(
            session,
            event_type="synthetic_data_seeded",
            entity_type="database",
            entity_id="seed",
            payload={
                "instruments": len(instruments),
                "market_rows": market_rows,
                "macro_rows": macro_rows,
                "start": str(args.start),
                "end": str(args.end),
            },
            actor="scripts/generate_synthetic_data.py",
        )

    log.info(
        "synthetic_data_seed_complete",
        instruments=len(instruments),
        market_rows=market_rows,
        macro_rows=macro_rows,
    )


if __name__ == "__main__":
    main()
