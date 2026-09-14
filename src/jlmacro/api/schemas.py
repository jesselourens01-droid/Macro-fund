"""Pydantic response models for the API. Kept separate from the ORM models so the wire
format can evolve independently of the database schema.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from jlmacro.models.enums import (
    AssetClass,
    Frequency,
    MacroCategory,
    RegimeLabel,
    TradeDirection,
    TradeStatus,
)


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


class VaRRequest(BaseModel):
    weights: dict[str, float]
    as_of: dt.date
    nav: float
    confidence: float | None = None
    horizon_days: int | None = None


class VaROut(BaseModel):
    symbols: list[str]
    as_of: dt.date
    confidence: float
    horizon_days: int
    methods: dict[str, dict[str, float]]  # method -> {var_pct, var_amount, es_pct, es_amount}


class HypotheticalStressRequest(BaseModel):
    weights: dict[str, float]
    scenario_id: str
    nav: float


class HypotheticalStressOut(BaseModel):
    scenario_id: str
    pnl_pct: float
    pnl_amount: float
    instrument_shocks: dict[str, float]
    unmapped_shock_keys: list[str]


class HistoricalStressRequest(BaseModel):
    weights: dict[str, float]
    scenario_id: str
    nav: float


class HistoricalStressOut(BaseModel):
    scenario_id: str
    start_date: dt.date
    end_date: dt.date
    pnl_pct: float
    pnl_amount: float
    instrument_returns: dict[str, float]
    missing_symbols: list[str]


class DrawdownGovernorOut(BaseModel):
    current_drawdown: float
    risk_budget_fraction: float
    defensive_mode: bool
    original_risk_budget: float | None
    governed_risk_budget: float | None


class BacktestRequest(BaseModel):
    symbols: list[str]
    start: dt.date
    end: dt.date
    nav0: float = 10_000_000.0
    rebalance_frequency_days: int | None = None
    weighting_method: str | None = None
    target_volatility: float | None = None


class BacktestPeriodOut(BaseModel):
    period_start: dt.date
    period_end: dt.date
    weights: dict[str, float]
    period_return: float
    nav_start: float
    nav_end: float


class BacktestOut(BaseModel):
    start: dt.date
    end: dt.date
    nav0: float
    periods: list[BacktestPeriodOut]
    total_return: float
    annualised_return: float
    annualised_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    calmar_ratio: float
    hit_rate: float


class WalkForwardRequest(BaseModel):
    symbols: list[str]
    start: dt.date
    end: dt.date
    window_days: int
    nav0: float = 10_000_000.0
    rebalance_frequency_days: int | None = None
    weighting_method: str | None = None
    target_volatility: float | None = None


class WalkForwardOut(BaseModel):
    windows: list[tuple[dt.date, dt.date]]
    results: list[BacktestOut]
    mean_sharpe_ratio: float
    worst_max_drawdown: float


class MonteCarloRequest(BaseModel):
    period_returns: list[float]
    nav0: float = 10_000_000.0
    num_simulations: int = 10_000
    horizon_periods: int | None = None
    seed: int | None = None


class MonteCarloOut(BaseModel):
    num_simulations: int
    horizon_periods: int
    nav0: float
    terminal_nav_percentiles: dict[str, float]
    probability_of_loss: float
    max_drawdown_percentiles: dict[str, float]
    probability_of_defensive_mode_breach: float


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    base_currency: str


class PortfolioCreateRequest(BaseModel):
    name: str
    base_currency: str = "AUD"


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_id: str
    portfolio_id: int
    instrument_id: int
    direction: TradeDirection
    status: TradeStatus
    thesis: str | None
    macro_score: float | None
    valuation_score: float | None
    trend_score: float | None
    positioning_score: float | None
    catalyst_score: float | None
    composite_score: float | None
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    portfolio_risk_pct: float | None
    position_size: float | None
    regime_at_entry: str | None
    pm_approved_by: str | None
    pm_approved_at: dt.datetime | None
    extra: dict | None
    created_at: dt.datetime
    updated_at: dt.datetime


class TradeIdeaCreateRequest(BaseModel):
    portfolio_id: int
    symbol: str
    direction: TradeDirection
    thesis: str
    macro_score: float | None = None
    valuation_score: float | None = None
    trend_score: float | None = None
    positioning_score: float | None = None
    catalyst_score: float | None = None
    composite_score: float | None = None
    entry_price: float | None = None
    target_price: float | None = None
    stop_price: float | None = None
    portfolio_risk_pct: float | None = None
    position_size: float | None = None
    regime_at_entry: str | None = None
    actor: str = "system"


class TradeTransitionRequest(BaseModel):
    new_status: TradeStatus
    actor: str
    reason: str | None = None


class TradeCloseRequest(BaseModel):
    exit_price: float
    actor: str
    reason: str | None = None


class InvestmentMemoOut(BaseModel):
    trade_id: str
    symbol: str
    instrument_name: str
    direction: str
    status: str
    thesis: str | None
    scores: dict[str, float | None]
    regime_at_entry: str | None
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    portfolio_risk_pct: float | None
    position_size: float | None
    pm_approved_by: str | None
    pm_approved_at: dt.datetime | None
    generated_at: dt.datetime
    markdown: str


class PostTradeReviewOut(BaseModel):
    trade_id: str
    symbol: str
    direction: str
    entry_price: float | None
    exit_price: float | None
    realised_return_pct: float | None
    composite_score_at_entry: float | None
    thesis_direction_correct: bool | None
    notes: str


class HealthOut(BaseModel):
    status: str
    environment: str
    live_trading_enabled: bool
