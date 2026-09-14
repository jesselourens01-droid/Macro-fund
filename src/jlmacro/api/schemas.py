"""Pydantic response models for the API. Kept separate from the ORM models so the wire
format can evolve independently of the database schema.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from jlmacro.models.enums import AssetClass, Frequency, MacroCategory, RegimeLabel


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


class RegimeSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country: str
    as_of: dt.date
    growth_score: float | None
    growth_bucket: int | None
    inflation_score: float | None
    inflation_bucket: int | None
    monetary_policy_score: float | None
    monetary_policy_bucket: int | None
    financial_conditions_score: float | None
    financial_conditions_bucket: int | None
    regime_label: RegimeLabel
    regime_confidence: float
    model_version: str


class RegimeStatusOut(BaseModel):
    country: str
    current: RegimeLabel
    confidence: float
    as_of: dt.date
    previous: RegimeLabel | None
    duration_periods: int
    transition_probabilities: dict[str, float]


class InvestmentScoreOut(BaseModel):
    instrument_symbol: str
    as_of: dt.date
    macro_score: float | None
    valuation_score: float | None
    trend_score: float | None
    positioning_score: float | None
    catalyst_score: float | None
    composite_score: float | None
    action: str
    suggested_risk_units: float
    detail: dict[str, object]


class CovarianceOut(BaseModel):
    symbols: list[str]
    as_of: dt.date
    method: str
    annualised_volatility: dict[str, float]
    covariance: dict[str, dict[str, float]]  # row symbol -> {column symbol -> value}


class PortfolioWeightsOut(BaseModel):
    symbols: list[str]
    as_of: dt.date
    method: str
    target_volatility: float
    gross_leverage: float
    portfolio_volatility: float
    weights: dict[str, float]
    risk_contributions: dict[str, float]  # fraction of portfolio variance, sums to 1


class PositionSizeOut(BaseModel):
    symbol: str
    as_of: dt.date
    direction: int
    risk_units: float
    risk_pct_nav: float
    stop_distance_pct: float | None
    risk_budget: float
    notional: float | None
    price: float | None


class ExposureRequest(BaseModel):
    weights: dict[str, float]  # symbol -> signed weight (fraction of NAV)
    as_of: dt.date
    covariance_method: str = "ledoit_wolf"


class ExposureOut(BaseModel):
    gross: float
    net: float
    by_asset_class: dict[str, float]
    by_country: dict[str, float]
    by_currency: dict[str, float]
    marginal_contribution_to_risk: dict[str, float]
    component_contribution_to_risk: dict[str, float]
    portfolio_volatility: float


class HealthOut(BaseModel):
    status: str
    environment: str
    live_trading_enabled: bool
