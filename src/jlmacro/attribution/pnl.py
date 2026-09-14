"""P&L attribution: buckets each trade's P&L (`jlmacro.nav.engine.compute_trade_pnl`)
by symbol, asset class, or direction, as of a given date. A trade contributes
exactly the same number here as it does to the portfolio NAV - attribution is a
breakdown of the same total, never a separately-computed figure that could disagree
with it.

This is P&L attribution only (which positions made or lost money) - decomposing *why*
within a single position (macro call vs. entry timing vs. noise, as
`jlmacro.trades.review`'s module docstring flags as still missing) is future work
once there's more than one closed trade's worth of history to learn a model from.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Trade
from jlmacro.nav.engine import compute_trade_pnl

GroupBy = Literal["symbol", "asset_class", "direction"]


def compute_pnl_attribution(
    session: Session, portfolio_id: int, *, as_of: dt.date, group_by: GroupBy = "symbol"
) -> dict[str, float]:
    trades = session.scalars(select(Trade).where(Trade.portfolio_id == portfolio_id)).all()

    buckets: dict[str, float] = {}
    for trade in trades:
        pnl = compute_trade_pnl(session, trade, as_of=as_of)
        if pnl == 0.0:
            continue

        if group_by == "direction":
            key = trade.direction.value
        else:
            instrument = session.get(Instrument, trade.instrument_id)
            if instrument is None:
                continue
            key = instrument.symbol if group_by == "symbol" else instrument.asset_class.value

        buckets[key] = buckets.get(key, 0.0) + pnl

    return buckets
