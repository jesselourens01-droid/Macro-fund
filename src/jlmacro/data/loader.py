"""Turns config/assets.yaml + provider records into database rows.

This is the one place that knows how the asset-universe YAML maps onto the Instrument
ORM model, and how provider records map onto MarketDataPoint/MacroDataPoint rows.

Two macro ingestion paths exist, because real providers differ in what they expose:

- Vintage providers (SyntheticMacroDataProvider, FredProvider) return records that
  already carry a genuine (release_date, revision_date) history - `ingest_macro_vintage_records`
  just inserts whichever (country, indicator_code, effective_date, revision_date)
  vintages aren't already in the database.
- Snapshot providers (RBAProvider, ABSProvider) only expose the *current* value for
  each period - there is no public vintage feed. `ingest_snapshot_macro_data` detects
  a "revision" locally by comparing against the latest value we already have, and
  stamps release_date/revision_date with the date we actually observed the change
  (never a date we didn't really know it), which is the only honest choice absent a
  real vintage history from the source.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.data.base import BaseMacroDataProvider
from jlmacro.data.macro.abs import ABSProvider
from jlmacro.data.macro.fred import FredProvider
from jlmacro.data.macro.rba import RBAProvider
from jlmacro.data.macro.synthetic import SyntheticMacroDataProvider
from jlmacro.data.market.synthetic import SyntheticMarketDataProvider
from jlmacro.data.quality import validate_macro_records
from jlmacro.models.enums import AssetClass, Frequency, MacroCategory
from jlmacro.models.instrument import Instrument
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.utils.logging import get_logger

logger = get_logger(__name__)

_ASSET_CLASS_BY_SECTION = {
    "equity_indices": AssetClass.EQUITY_INDEX,
    "rates": AssetClass.RATE,
    "fx": AssetClass.FX,
    "commodities": AssetClass.COMMODITY,
}

_KNOWN_FIELDS = {"symbol", "name", "country", "currency", "calendar"}


def seed_instruments(session: Session) -> list[Instrument]:
    """Idempotently upsert the Instrument table from config/assets.yaml."""
    universe = load_yaml_config("assets")
    created: list[Instrument] = []

    for section, asset_class in _ASSET_CLASS_BY_SECTION.items():
        for entry in universe.get(section, []):
            symbol = entry["symbol"]
            existing = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
            currency = entry.get("currency") or entry.get("quote_currency", "USD")
            metadata = {k: v for k, v in entry.items() if k not in _KNOWN_FIELDS}

            if existing:
                existing.name = entry["name"]
                existing.asset_class = asset_class
                existing.country = entry.get("country")
                existing.currency = currency
                existing.calendar = entry.get("calendar")
                existing.metadata_json = metadata or None
                created.append(existing)
                continue

            instrument = Instrument(
                symbol=symbol,
                name=entry["name"],
                asset_class=asset_class,
                country=entry.get("country"),
                currency=currency,
                calendar=entry.get("calendar"),
                metadata_json=metadata or None,
            )
            session.add(instrument)
            created.append(instrument)

    session.flush()
    return created


def seed_market_data(
    session: Session,
    instruments: list[Instrument],
    *,
    start: dt.date,
    end: dt.date,
) -> int:
    """Generate and insert synthetic price history for the given instruments.

    Skips any (instrument, timestamp) pairs already present, so this is safe to re-run.
    """
    provider = SyntheticMarketDataProvider()
    asset_classes = {inst.symbol: inst.asset_class.value for inst in instruments}
    symbols = [inst.symbol for inst in instruments]
    instrument_by_symbol = {inst.symbol: inst for inst in instruments}

    records = provider.fetch(
        identifiers=symbols,
        start=start,
        end=end,
        asset_classes=asset_classes,
        calendar="NYSE",
    )

    existing_keys: set[tuple] = {
        tuple(row)
        for row in session.execute(
            select(MarketDataPoint.instrument_id, MarketDataPoint.timestamp)
        ).all()
    }

    inserted = 0
    for rec in records:
        instrument = instrument_by_symbol[rec["symbol"]]
        key = (instrument.id, rec["timestamp"])
        if key in existing_keys:
            continue
        session.add(
            MarketDataPoint(
                instrument_id=instrument.id,
                timestamp=rec["timestamp"],
                frequency=Frequency(rec["frequency"]),
                open=rec["open"],
                high=rec["high"],
                low=rec["low"],
                close=rec["close"],
                volume=rec["volume"],
                source=rec["source"],
                effective_date=rec["effective_date"],
                release_date=rec["release_date"],
                revision_date=rec["revision_date"],
                original_value=rec["original_value"],
                revised_value=rec["revised_value"],
            )
        )
        existing_keys.add(key)
        inserted += 1

    session.flush()
    return inserted


def _all_indicator_codes() -> list[str]:
    config = load_yaml_config("macro_indicators")
    return [item["code"] for category in config.get("indicators", {}).values() for item in category]


def _macro_vintage_keys(session: Session) -> set[tuple]:
    return {
        tuple(row)
        for row in session.execute(
            select(
                MacroDataPoint.country,
                MacroDataPoint.indicator_code,
                MacroDataPoint.effective_date,
                MacroDataPoint.revision_date,
            )
        ).all()
    }


def _log_quality_issues(source: str, records: list[dict]) -> None:
    report = validate_macro_records(records)
    for issue in report.issues:
        log = logger.warning if issue.severity == "warning" else logger.error
        log(
            "data_quality_issue",
            source=source,
            check=issue.check,
            message=issue.message,
            **issue.context,
        )
    if report.has_errors:
        raise ValueError(f"{source} data failed quality validation: {len(report)} issue(s) found")


def ingest_macro_vintage_records(session: Session, records: list[dict]) -> int:
    """Insert MacroDataPoint rows for records that already carry a real
    (release_date, revision_date) vintage - used for SyntheticMacroDataProvider and
    FredProvider output. Skips any (country, indicator_code, effective_date,
    revision_date) vintage already present, so this is safe to re-run.
    """
    existing_keys = _macro_vintage_keys(session)

    inserted = 0
    for rec in records:
        key = (rec["country"], rec["indicator_code"], rec["effective_date"], rec["revision_date"])
        if key in existing_keys:
            continue
        session.add(
            MacroDataPoint(
                country=rec["country"],
                indicator_code=rec["indicator_code"],
                category=MacroCategory(rec["category"]),
                frequency=Frequency(rec["frequency"]),
                value=rec["value"],
                original_value=rec["original_value"],
                revised_value=rec["revised_value"],
                source=rec["source"],
                effective_date=rec["effective_date"],
                release_date=rec["release_date"],
                revision_date=rec["revision_date"],
            )
        )
        existing_keys.add(key)
        inserted += 1

    session.flush()
    return inserted


def seed_macro_data(session: Session, *, start: dt.date, end: dt.date) -> int:
    """Generate and insert synthetic macro observations for the configured countries
    and indicators (config/macro_indicators.yaml). Safe to re-run.
    """
    config = load_yaml_config("macro_indicators")
    countries = config.get("countries", [])
    indicator_codes = _all_indicator_codes()

    provider = SyntheticMacroDataProvider()
    records = provider.fetch(identifiers=indicator_codes, start=start, end=end, countries=countries)
    return ingest_macro_vintage_records(session, records)


def ingest_fred_macro_data(
    session: Session,
    *,
    countries: list[str],
    start: dt.date,
    end: dt.date,
    indicator_codes: list[str] | None = None,
    api_key: str | None = None,
) -> int:
    """Fetch real US (and any other FRED-mapped country's) macro data from FRED,
    including its full ALFRED vintage history, and insert any new vintages.
    """
    indicator_codes = indicator_codes or _all_indicator_codes()
    with FredProvider(api_key=api_key) as provider:
        records = provider.fetch(
            identifiers=indicator_codes, start=start, end=end, countries=countries
        )

    _log_quality_issues("FRED", records)
    return ingest_macro_vintage_records(session, records)


def _latest_macro_row(
    session: Session, country: str, indicator_code: str, effective_date: dt.date
) -> MacroDataPoint | None:
    stmt = (
        select(MacroDataPoint)
        .where(
            MacroDataPoint.country == country,
            MacroDataPoint.indicator_code == indicator_code,
            MacroDataPoint.effective_date == effective_date,
        )
        .order_by(MacroDataPoint.revision_date.desc(), MacroDataPoint.id.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def ingest_snapshot_macro_data(
    session: Session,
    provider: BaseMacroDataProvider,
    *,
    countries: list[str],
    start: dt.date,
    end: dt.date,
    indicator_codes: list[str] | None = None,
    as_of: dt.date | None = None,
) -> int:
    """Ingest a provider that only exposes current values (RBA, ABS).

    Creates a new MacroDataPoint revision row only when the fetched value differs from
    the latest value we already have for that period, using `as_of` (defaulting to
    today) as the knowledge date for both release_date (the first time we saw this
    period at all) and revision_date (this specific vintage) - the only honest choice
    when the source itself doesn't expose when a value was actually first published.
    """
    indicator_codes = indicator_codes or _all_indicator_codes()
    as_of = as_of or dt.datetime.now(dt.UTC).date()

    records = provider.fetch(identifiers=indicator_codes, start=start, end=end, countries=countries)
    _log_quality_issues(provider.name, records)

    changed = 0
    for rec in records:
        existing = _latest_macro_row(
            session, rec["country"], rec["indicator_code"], rec["effective_date"]
        )

        if existing is not None and existing.value == rec["value"]:
            continue  # No change since our last ingest - nothing to record.

        if existing is not None and existing.revision_date == as_of:
            # Re-ingested today with a different value than earlier today: update the
            # same day's row in place rather than create a second same-day vintage.
            existing.value = rec["value"]
            existing.revised_value = rec["value"]
            changed += 1
            continue

        session.add(
            MacroDataPoint(
                country=rec["country"],
                indicator_code=rec["indicator_code"],
                category=MacroCategory(rec["category"]),
                frequency=Frequency(rec["frequency"]),
                value=rec["value"],
                original_value=existing.original_value if existing is not None else rec["value"],
                revised_value=rec["value"] if existing is not None else None,
                source=rec["source"],
                effective_date=rec["effective_date"],
                release_date=existing.release_date if existing is not None else as_of,
                revision_date=as_of,
            )
        )
        changed += 1

    session.flush()
    return changed


def ingest_rba_macro_data(
    session: Session,
    *,
    countries: list[str] | None = None,
    start: dt.date,
    end: dt.date,
    indicator_codes: list[str] | None = None,
    as_of: dt.date | None = None,
) -> int:
    with RBAProvider() as provider:
        return ingest_snapshot_macro_data(
            session,
            provider,
            countries=countries or ["AU"],
            start=start,
            end=end,
            indicator_codes=indicator_codes,
            as_of=as_of,
        )


def ingest_abs_macro_data(
    session: Session,
    *,
    countries: list[str] | None = None,
    start: dt.date,
    end: dt.date,
    indicator_codes: list[str] | None = None,
    as_of: dt.date | None = None,
) -> int:
    with ABSProvider() as provider:
        return ingest_snapshot_macro_data(
            session,
            provider,
            countries=countries or ["AU"],
            start=start,
            end=end,
            indicator_codes=indicator_codes,
            as_of=as_of,
        )
