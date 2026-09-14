"""Turns config/assets.yaml + the synthetic providers into database rows.

This is the one place that knows how the asset-universe YAML maps onto the Instrument
ORM model, and how provider records map onto MarketDataPoint/MacroDataPoint rows. Real
Phase 2 provider adapters plug into the same seed_market_data/seed_macro_data shape.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.data.macro.synthetic import SyntheticMacroDataProvider
from jlmacro.data.market.synthetic import SyntheticMarketDataProvider
from jlmacro.models.enums import AssetClass, Frequency, MacroCategory
from jlmacro.models.instrument import Instrument
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.market_data import MarketDataPoint

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


def seed_macro_data(session: Session, *, start: dt.date, end: dt.date) -> int:
    """Generate and insert synthetic macro observations for the configured countries
    and indicators (config/macro_indicators.yaml). Safe to re-run.
    """
    config = load_yaml_config("macro_indicators")
    countries = config.get("countries", [])
    indicator_codes = [
        item["code"] for category in config.get("indicators", {}).values() for item in category
    ]

    provider = SyntheticMacroDataProvider()
    records = provider.fetch(
        identifiers=indicator_codes,
        start=start,
        end=end,
        countries=countries,
    )

    existing_keys: set[tuple] = {
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
