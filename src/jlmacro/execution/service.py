"""Connects the broker abstraction to the trade lifecycle (Phase 8): submits an
order for a trade's instrument, and only on an actual fill does it touch the trade
row - confirming `entry_price` (rather than trusting whatever estimate was recorded
at idea time) and driving `OPEN`/`CLOSED` through the same audited
`jlmacro.trades.lifecycle.transition` path every other state change uses. A
rejected or still-`PENDING` order leaves the trade exactly where it was; nothing
here ever half-opens or half-closes a trade.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from jlmacro.execution.base import BaseBroker, OrderRequest, OrderResult, OrderSide, OrderStatus
from jlmacro.models.enums import TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Trade
from jlmacro.trades.lifecycle import transition
from jlmacro.trades.review import close_trade


def direction_to_side(direction: TradeDirection, *, closing: bool = False) -> OrderSide:
    """LONG opens with a BUY and closes with a SELL; SHORT is the mirror image."""
    if direction == TradeDirection.LONG:
        return OrderSide.SELL if closing else OrderSide.BUY
    return OrderSide.BUY if closing else OrderSide.SELL


def _symbol_for_trade(session: Session, trade: Trade) -> str:
    instrument = session.get(Instrument, trade.instrument_id)
    if instrument is None:
        raise ValueError(f"instrument {trade.instrument_id} for trade {trade.trade_id} not found")
    return instrument.symbol


def open_trade_via_broker(
    session: Session,
    broker: BaseBroker,
    trade: Trade,
    *,
    quantity: float,
    as_of: dt.date,
    actor: str,
) -> OrderResult:
    if trade.status != TradeStatus.APPROVED:
        raise ValueError(
            f"trade {trade.trade_id} must be APPROVED before an opening order can be "
            f"submitted; it is {trade.status.value}"
        )

    symbol = _symbol_for_trade(session, trade)
    request = OrderRequest(
        symbol=symbol,
        side=direction_to_side(trade.direction),
        quantity=quantity,
        trade_id=trade.trade_id,
    )
    result = broker.submit_order(request, as_of=as_of)

    if result.status == OrderStatus.FILLED:
        assert result.filled_price is not None  # guaranteed by OrderStatus.FILLED
        trade.entry_price = result.filled_price
        transition(
            session,
            trade,
            TradeStatus.OPEN,
            actor=actor,
            reason=f"filled via {broker.name} broker at {result.filled_price}",
        )
    return result


def close_trade_via_broker(
    session: Session,
    broker: BaseBroker,
    trade: Trade,
    *,
    quantity: float,
    as_of: dt.date,
    actor: str,
) -> OrderResult:
    if trade.status not in (TradeStatus.OPEN, TradeStatus.REDUCE):
        raise ValueError(
            f"trade {trade.trade_id} must be OPEN or REDUCE to submit a closing order; "
            f"it is {trade.status.value}"
        )

    symbol = _symbol_for_trade(session, trade)
    request = OrderRequest(
        symbol=symbol,
        side=direction_to_side(trade.direction, closing=True),
        quantity=quantity,
        trade_id=trade.trade_id,
    )
    result = broker.submit_order(request, as_of=as_of)

    if result.status == OrderStatus.FILLED:
        assert result.filled_price is not None  # guaranteed by OrderStatus.FILLED
        close_trade(
            session,
            trade,
            exit_price=result.filled_price,
            actor=actor,
            reason=f"closed via {broker.name} broker at {result.filled_price}",
        )
    return result
