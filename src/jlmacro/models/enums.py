"""Shared enums for the ORM models."""

from __future__ import annotations

import enum


class AssetClass(str, enum.Enum):
    EQUITY_INDEX = "equity_index"
    RATE = "rate"
    FX = "fx"
    COMMODITY = "commodity"
    CREDIT = "credit"
    CRYPTO = "crypto"


class Frequency(str, enum.Enum):
    TICK = "tick"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class MacroCategory(str, enum.Enum):
    GROWTH = "growth"
    INFLATION = "inflation"
    MONETARY_POLICY = "monetary_policy"
    FINANCIAL_CONDITIONS = "financial_conditions"


class TradeStatus(str, enum.Enum):
    IDEA = "idea"
    WATCHLIST = "watchlist"
    APPROVED = "approved"
    OPEN = "open"
    REDUCE = "reduce"
    CLOSED = "closed"
    INVALIDATED = "invalidated"


class TradeDirection(str, enum.Enum):
    LONG = "long"
    SHORT = "short"
