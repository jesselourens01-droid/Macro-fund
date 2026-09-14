"""Feature/label construction for the ML research layer.

Features are exactly the Phase 4 composite score's own components
(`compute_investment_score(..., as_of=date)`) - point-in-time correct by
construction, since that's the same function every rule-based signal in this
platform already relies on. The label is the forward return's sign over a fixed
horizon, which is necessarily *not* point-in-time (a training label is allowed to
look into the future; a decision input never is) - `jlmacro.backtest.walk_forward`'s
chronological train/test split is what keeps that forward-looking label from ever
leaking into a fold's training features for a later date.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy.orm import Session

from jlmacro.models.signals import compute_investment_score
from jlmacro.models.signals.pit import point_in_time_closes

FEATURE_COLUMNS = [
    "macro_score",
    "valuation_score",
    "trend_score",
    "positioning_score",
    "catalyst_score",
]


def _forward_return(
    session: Session, symbol: str, *, as_of: dt.date, horizon_days: int
) -> float | None:
    target_date = as_of + dt.timedelta(days=horizon_days)
    history = point_in_time_closes(
        session, symbol, as_of=target_date, window_days=horizon_days + 15
    )
    if not history:
        return None

    # If price history doesn't actually extend to near the target date, the horizon
    # runs off the end of what's available - report "no label yet" rather than
    # fabricating a return from a stale last price capped short of the target.
    last_available_date = history[-1][0]
    if last_available_date < target_date - dt.timedelta(days=5):
        return None

    on_or_before_start = [c for d, c in history if d <= as_of]
    on_or_before_target = [c for d, c in history if d <= target_date]
    if not on_or_before_start or not on_or_before_target:
        return None
    start_price = on_or_before_start[-1]
    end_price = on_or_before_target[-1]
    if start_price == 0:
        return None
    return (end_price / start_price) - 1.0


def build_feature_dataset(
    session: Session,
    symbols: list[str],
    dates: list[dt.date],
    *,
    horizon_days: int = 21,
) -> pd.DataFrame:
    """One row per (symbol, date): the five composite-score components as features,
    `forward_return` and its sign `target` (1 if positive, else 0) as the label. A
    row with any missing feature or an unresolvable forward return is dropped -
    scikit-learn models can't train on `None`, and silently imputing a score
    component would fabricate a signal that was never actually available.
    """
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        for as_of in dates:
            score = compute_investment_score(session, symbol, as_of=as_of)
            features = {
                "macro_score": score.macro_score,
                "valuation_score": score.valuation_score,
                "trend_score": score.trend_score,
                "positioning_score": score.positioning_score,
                "catalyst_score": score.catalyst_score,
            }
            if any(v is None for v in features.values()):
                continue

            forward_return = _forward_return(
                session, symbol, as_of=as_of, horizon_days=horizon_days
            )
            if forward_return is None:
                continue

            rows.append(
                {
                    "symbol": symbol,
                    "date": as_of,
                    **features,
                    "forward_return": forward_return,
                    "target": int(forward_return > 0),
                }
            )

    return pd.DataFrame(rows)
