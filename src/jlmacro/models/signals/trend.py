"""Multi-timeframe trend engine.

Deliberately avoids a single moving-average crossover (the platform spec calls this
out explicitly) by combining volatility-adjusted momentum across several lookback
horizons (20/60/120/200 trading days by default) with a trend-persistence measure.
All computed point-in-time (jlmacro.models.signals.pit) so replaying an earlier as_of
during a future backtest never sees a later price.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.signals.pit import point_in_time_closes


@dataclass
class TrendResult:
    # Signed trend strength in -100..+100 (positive = uptrend); None if there isn't
    # enough history yet.
    score: float | None
    label: str  # strong_long/long/neutral/short/strong_short/unknown
    returns: dict[int, float | None] = field(default_factory=dict)  # {lookback_days: pct_return}
    atr: float | None = None
    persistence: float | None = (
        None  # fraction of recent daily moves matching the trend's direction
    )


def _daily_returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1] != 0]


def _vol_adjusted_momentum(closes: list[float], lookback: int) -> float | None:
    """Annualised return over the lookback, divided by annualised volatility of daily
    returns within that same window - a Sharpe-like measure, so a 30% rally on
    calm markets scores as a stronger trend than the same rally achieved through
    whipsawing, and so trends are comparable across very different volatility regimes
    (equities vs. FX vs. rates).
    """
    if len(closes) <= lookback:
        return None
    window = closes[-(lookback + 1) :]
    total_return = window[-1] / window[0] - 1
    daily = _daily_returns(window)
    if len(daily) < 2:
        return None
    mean = sum(daily) / len(daily)
    variance = sum((r - mean) ** 2 for r in daily) / len(daily)
    annualised_vol = math.sqrt(variance) * math.sqrt(252)
    annualised_return = (1 + total_return) ** (252 / lookback) - 1
    if annualised_vol == 0:
        # A perfectly steady (zero-volatility) move is a maximally strong trend, not
        # a neutral one - a naive 0/0 guard would wrongly read a riskless grind as
        # "no trend." Cap at a large-but-finite magnitude, well past where the final
        # tanh scaling saturates, rather than returning an unbounded value.
        return 0.0 if annualised_return == 0 else math.copysign(10.0, annualised_return)
    return annualised_return / annualised_vol


def _average_true_range_proxy(closes: list[float], period: int) -> float | None:
    """Close-to-close absolute change average over `period` - a simplified True Range
    proxy. Real ATR needs intrabar high/low; not every provider (e.g. a macro-style
    rate "price" series) reliably carries meaningful high/low, so this stays correct
    off closes alone, at the cost of understating true intrabar range.
    """
    if len(closes) <= period:
        return None
    window = closes[-(period + 1) :]
    diffs = [abs(window[i] - window[i - 1]) for i in range(1, len(window))]
    return sum(diffs) / len(diffs)


def _persistence(closes: list[float], lookback: int) -> float | None:
    """Fraction of daily moves over the lookback that agree in sign with the
    lookback's overall direction - a high fraction means a steady grind, a low
    fraction means the same net move came from a choppy/whipsawing path.
    """
    if len(closes) <= lookback:
        return None
    window = closes[-(lookback + 1) :]
    daily = _daily_returns(window)
    if not daily:
        return None
    overall_up = window[-1] >= window[0]
    matching = sum(1 for r in daily if (r >= 0) == overall_up)
    return matching / len(daily)


def compute_trend(session: Session, symbol: str, *, as_of: dt.date) -> TrendResult:
    config = load_yaml_config("signals")["trend"]
    lookbacks: list[int] = config["lookback_periods_days"]
    window_days = (max(lookbacks) + config["atr_period_days"]) * 2 + 30

    closes = [
        close
        for _, close in point_in_time_closes(session, symbol, as_of=as_of, window_days=window_days)
    ]

    if len(closes) < config["min_observations"]:
        return TrendResult(score=None, label="unknown")

    returns: dict[int, float | None] = {}
    momenta: list[float] = []
    for lookback in lookbacks:
        returns[lookback] = (
            closes[-1] / closes[-1 - lookback] - 1 if len(closes) > lookback else None
        )
        momentum = _vol_adjusted_momentum(closes, lookback)
        if momentum is not None:
            momenta.append(momentum)

    atr = _average_true_range_proxy(closes, config["atr_period_days"])
    persistence = _persistence(closes, config["persistence_lookback_days"])

    if not momenta:
        return TrendResult(
            score=None, label="unknown", returns=returns, atr=atr, persistence=persistence
        )

    composite = sum(momenta) / len(momenta)

    if composite >= config["strong_threshold"]:
        label = "strong_long"
    elif composite >= config["weak_threshold"]:
        label = "long"
    elif composite <= -config["strong_threshold"]:
        label = "strong_short"
    elif composite <= -config["weak_threshold"]:
        label = "short"
    else:
        label = "neutral"

    # Bounded, monotonic map of the (unbounded) Sharpe-like composite into -100..100 -
    # the label above is decided on the raw composite; this score is for numeric use
    # (e.g. jlmacro.models.signals.composite) where a bounded scale matters more than
    # the exact Sharpe magnitude.
    score = 100.0 * math.tanh(composite / 2.0)

    return TrendResult(score=score, label=label, returns=returns, atr=atr, persistence=persistence)
