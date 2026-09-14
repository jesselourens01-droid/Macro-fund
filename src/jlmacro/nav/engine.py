"""NAV computation: `starting_capital + sum of every trade's P&L as of a date`, where
each trade's P&L is realised (its recorded exit price, if closed by that date) or
unrealised (marked to the latest point-in-time close, if still open) - never a
persisted running ledger, so it can be recomputed for any historical `as_of` from
the Trade rows alone (the same "recompute from source, don't cache a second copy"
discipline `jlmacro.trades.memo` uses for memos).

A trade only contributes once it has actually reached `OPEN` (read from its own
`extra["lifecycle_history"]`, the audit trail `jlmacro.trades.lifecycle` writes) -
an `IDEA`/`WATCHLIST`/`APPROVED` trade has no P&L, real or otherwise, because no
capital is committed to it yet.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.models.enums import TradeDirection
from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Trade
from jlmacro.models.signals.pit import point_in_time_closes


def _first_transition_date(trade: Trade, to_status: str) -> dt.date | None:
    for entry in (trade.extra or {}).get("lifecycle_history", []):
        if entry["to"] == to_status:
            return dt.datetime.fromisoformat(entry["at"]).date()
    return None


def compute_trade_pnl(session: Session, trade: Trade, *, as_of: dt.date) -> float:
    """Dollar P&L for one trade as of `as_of`. Zero if the trade hasn't reached
    `OPEN` by that date, or if the sizing/pricing fields it needs are missing -
    fails safe to "no contribution" rather than guessing.
    """
    open_date = _first_transition_date(trade, "open")
    if open_date is None or open_date > as_of:
        return 0.0
    if trade.position_size is None or trade.entry_price is None or trade.entry_price == 0:
        return 0.0

    sign = 1 if trade.direction == TradeDirection.LONG else -1

    close_date = _first_transition_date(trade, "closed")
    if close_date is not None and close_date <= as_of:
        exit_price = (trade.extra or {}).get("exit_price")
        if exit_price is None:
            return 0.0
        price_return = (exit_price / trade.entry_price) - 1.0
        return trade.position_size * sign * price_return

    instrument = session.get(Instrument, trade.instrument_id)
    if instrument is None:
        return 0.0
    history = point_in_time_closes(session, instrument.symbol, as_of=as_of, window_days=10)
    if not history:
        return 0.0
    latest_price = history[-1][1]
    price_return = (latest_price / trade.entry_price) - 1.0
    return trade.position_size * sign * price_return


def compute_portfolio_pnl(session: Session, portfolio_id: int, *, as_of: dt.date) -> float:
    trades = session.scalars(select(Trade).where(Trade.portfolio_id == portfolio_id)).all()
    return sum(compute_trade_pnl(session, trade, as_of=as_of) for trade in trades)


def compute_nav(
    session: Session, portfolio_id: int, *, as_of: dt.date, starting_capital: float
) -> float:
    return starting_capital + compute_portfolio_pnl(session, portfolio_id, as_of=as_of)


def nav_history(
    session: Session,
    portfolio_id: int,
    *,
    start: dt.date,
    end: dt.date,
    starting_capital: float,
    frequency_days: int = 1,
) -> pd.Series:
    dates: list[dt.date] = []
    current = start
    while current <= end:
        dates.append(current)
        current = current + dt.timedelta(days=frequency_days)
    if dates[-1] != end:
        dates.append(end)

    navs = [
        compute_nav(session, portfolio_id, as_of=d, starting_capital=starting_capital)
        for d in dates
    ]
    return pd.Series(navs, index=pd.Index(dates, name="date"))


def high_water_mark_series(nav_series: pd.Series) -> pd.Series:
    return nav_series.cummax()


def drawdown_series(nav_series: pd.Series) -> pd.Series:
    hwm = high_water_mark_series(nav_series)
    return (nav_series / hwm) - 1.0


def current_drawdown(
    session: Session,
    portfolio_id: int,
    *,
    as_of: dt.date,
    start: dt.date,
    starting_capital: float,
    frequency_days: int = 1,
) -> float:
    """Feeds directly into `jlmacro.risk.drawdown.risk_budget_fraction_for_drawdown` -
    the real drawdown figure that module's docstring says Phase 9 would supply.
    """
    series = nav_history(
        session,
        portfolio_id,
        start=start,
        end=as_of,
        starting_capital=starting_capital,
        frequency_days=frequency_days,
    )
    if series.empty:
        return 0.0
    return float(drawdown_series(series).iloc[-1])
