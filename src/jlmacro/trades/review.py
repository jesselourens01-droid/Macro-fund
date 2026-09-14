"""Closing a trade and reviewing it afterwards.

`close_trade` is the only way a trade's exit price gets recorded - it stores
`exit_price`/`closed_at` on the row (in `extra`, the same JSON escape hatch the
lifecycle history uses) and drives the state machine to `CLOSED` through
`jlmacro.trades.lifecycle.transition`, so a close is always audited exactly like any
other transition.

`generate_post_trade_review` then asks the one question a memo can't answer at idea
time: did the thesis turn out to be right? It compares the realised, direction-
adjusted return against the entry-time composite score's implied view (bullish for a
long, bearish for a short) - nothing more elaborate than that; a proper attribution
breakdown (how much of the return came from the macro call vs. the entry timing vs.
noise) is Phase 9's job once there's a NAV/attribution engine to lean on.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from jlmacro.models.enums import TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Trade
from jlmacro.trades.lifecycle import transition


def close_trade(
    session: Session, trade: Trade, *, exit_price: float, actor: str, reason: str | None = None
) -> Trade:
    extra = dict(trade.extra or {})
    extra["exit_price"] = exit_price
    extra["closed_at"] = dt.datetime.now(dt.UTC).isoformat()
    trade.extra = extra
    return transition(session, trade, TradeStatus.CLOSED, actor=actor, reason=reason)


@dataclass
class PostTradeReview:
    trade_id: str
    symbol: str
    direction: str
    entry_price: float | None
    exit_price: float | None
    realised_return_pct: float | None
    composite_score_at_entry: float | None
    thesis_direction_correct: bool | None
    notes: str


def generate_post_trade_review(session: Session, trade: Trade) -> PostTradeReview:
    if trade.status != TradeStatus.CLOSED:
        raise ValueError(
            f"post-trade review requires a CLOSED trade; {trade.trade_id} is {trade.status.value}"
        )

    instrument = session.get(Instrument, trade.instrument_id)
    if instrument is None:
        raise ValueError(f"instrument {trade.instrument_id} for trade {trade.trade_id} not found")

    exit_price = (trade.extra or {}).get("exit_price")
    realised_return_pct: float | None = None
    thesis_direction_correct: bool | None = None
    notes: str

    if trade.entry_price is not None and exit_price is not None and trade.entry_price != 0:
        raw_return = (exit_price / trade.entry_price) - 1.0
        sign = 1 if trade.direction == TradeDirection.LONG else -1
        realised_return_pct = raw_return * sign
        thesis_direction_correct = realised_return_pct > 0
        notes = (
            f"Realised {realised_return_pct:+.2%} on a {trade.direction.value} thesis - "
            f"{'consistent with' if thesis_direction_correct else 'against'} the entry-time view."
        )
    else:
        notes = "Entry or exit price missing - realised return not computable."

    return PostTradeReview(
        trade_id=trade.trade_id,
        symbol=instrument.symbol,
        direction=trade.direction.value,
        entry_price=trade.entry_price,
        exit_price=exit_price,
        realised_return_pct=realised_return_pct,
        composite_score_at_entry=trade.composite_score,
        thesis_direction_correct=thesis_direction_correct,
        notes=notes,
    )
