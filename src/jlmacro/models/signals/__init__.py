"""Quantitative signal engine: Trend, Valuation, Positioning, Catalyst and the
Composite Investment Score (Phase 4).

Trend is a real, first-principles computation over price history. Valuation is real
for FX/RATE (real-rate differential / real yield) and an honestly-documented proxy for
EQUITY_INDEX/COMMODITY, since this platform doesn't yet have real earnings or
futures-curve data. Positioning and Catalyst are both documented proxies (RSI-based
crowding, and projected-cadence/self-referential-surprise respectively), since there
is no real CFTC/options/consensus-calendar data source yet. See each module's
docstring for exactly what stands in for what, and config/signals.yaml's top comment.
"""

from jlmacro.models.signals.catalyst import (
    CatalystEvent,
    CatalystResult,
    catalyst_score,
    upcoming_catalysts,
)
from jlmacro.models.signals.composite import InvestmentScore, compute_investment_score
from jlmacro.models.signals.macro_factor import MacroFactorResult, compute_macro_factor
from jlmacro.models.signals.positioning import PositioningResult, compute_positioning
from jlmacro.models.signals.trend import TrendResult, compute_trend
from jlmacro.models.signals.valuation import ValuationResult, compute_valuation

__all__ = [
    "CatalystEvent",
    "CatalystResult",
    "InvestmentScore",
    "MacroFactorResult",
    "PositioningResult",
    "TrendResult",
    "ValuationResult",
    "catalyst_score",
    "compute_investment_score",
    "compute_macro_factor",
    "compute_positioning",
    "compute_trend",
    "compute_valuation",
    "upcoming_catalysts",
]
