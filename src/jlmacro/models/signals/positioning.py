"""Positioning engine.

This platform does not yet have a real CFTC/open-interest/ETF-flow/options-skew data
source (Phase 2+ work - see config/signals.yaml's top comment). Rather than leave
positioning entirely unimplemented, this uses a well-known technical stand-in that
quant macro desks reach for exactly when real positioning data isn't available:
Wilder's RSI(14) as a price-based crowding proxy. It is explicitly NOT CFTC/options
positioning - swap in a real provider behind `compute_positioning`'s signature once
one exists, with no caller changes needed.

Framed, like the other signal engines, as "attractiveness of a LONG position" (50 =
neutral) - but contrarian here: an *overbought* (crowded-long) reading is a headwind
for adding to a long (squeeze/reversal risk), so it lowers the score; an *oversold*
(crowded-short) reading is a tailwind (potential short squeeze / mean reversion), so
it raises the score.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.signals.pit import point_in_time_closes


@dataclass
class PositioningResult:
    score: float | None  # 0-100, contrarian re: crowding; None if not enough history
    label: str  # extreme_long/crowded_long/neutral/crowded_short/extreme_short/unknown
    rsi: float | None = None


def _wilders_rsi(closes: list[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    window = closes[-(period + 1) :]
    gains = []
    losses = []
    for i in range(1, len(window)):
        change = window[i] - window[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def compute_positioning(session: Session, symbol: str, *, as_of: dt.date) -> PositioningResult:
    config = load_yaml_config("signals")["positioning"]
    period = config["rsi_period_days"]

    closes = [
        close
        for _, close in point_in_time_closes(
            session, symbol, as_of=as_of, window_days=(period + 5) * 3
        )
    ]
    if len(closes) < config["min_observations"]:
        return PositioningResult(score=None, label="unknown")

    rsi = _wilders_rsi(closes, period)
    if rsi is None:
        return PositioningResult(score=None, label="unknown")

    if rsi >= config["extreme_long_rsi"]:
        label = "extreme_long"
    elif rsi >= config["crowded_long_rsi"]:
        label = "crowded_long"
    elif rsi <= config["extreme_short_rsi"]:
        label = "extreme_short"
    elif rsi <= config["crowded_short_rsi"]:
        label = "crowded_short"
    else:
        label = "neutral"

    return PositioningResult(score=100.0 - rsi, label=label, rsi=rsi)
