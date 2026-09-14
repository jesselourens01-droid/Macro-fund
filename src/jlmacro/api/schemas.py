"""Pydantic response models for the API. Kept separate from the ORM models so the wire
format can evolve independently of the database schema.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from jlmacro.models.enums import AssetClass, Frequency, MacroCategory


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    asset_class: AssetClass
    country: str | None
    currency: str
    calendar: str | None
    is_active: bool


class MarketDataPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: int
    timestamp: dt.datetime
    frequency: Frequency
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None
    source: str


class MacroDataPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country: str
    indicator_code: str
    category: MacroCategory
    frequency: Frequency
    effective_date: dt.date
    release_date: dt.date | None
    revision_date: dt.date | None
    value: float
    original_value: float | None
    revised_value: float | None
    source: str


class HealthOut(BaseModel):
    status: str
    environment: str
    live_trading_enabled: bool
