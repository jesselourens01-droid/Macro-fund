"""Paper broker: simulates fills against this platform's own point-in-time price
history rather than any real venue - the only broker implementation this codebase
has, and (per the platform spec) the only one allowed to exist while live trading is
disabled.

Fill model (v1, documented as a simplification - there is no real order book here,
only daily closes): a `MARKET` order fills immediately at the latest point-in-time
close for `as_of`. A `LIMIT` order fills at that same close if it's marketable (a BUY
limit at or above the close, a SELL limit at or below it) - not at the limit price
itself, since a real fill would happen at the prevailing price once marketable, not
necessarily exactly at the limit. A non-marketable limit stays `PENDING` forever in
this v1 (there is no order book to re-check it against later); an order for a symbol
with no price data as of `as_of` is `REJECTED`, never silently dropped.

Every order is logged through `jlmacro.utils.audit.log_event`, live or paper - this
is exactly the kind of event the platform's compliance trail exists for.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from jlmacro.execution.base import (
    BaseBroker,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    new_order_id,
)
from jlmacro.execution.safeguards import assert_broker_permitted
from jlmacro.models.signals.pit import point_in_time_closes
from jlmacro.utils.audit import log_event


class PaperBroker(BaseBroker):
    name = "paper"

    def __init__(self, session: Session) -> None:
        assert_broker_permitted(self.name)
        self._session = session
        self._orders: dict[str, OrderResult] = {}

    def submit_order(self, request: OrderRequest, *, as_of: dt.date) -> OrderResult:
        order_id = new_order_id()
        history = point_in_time_closes(self._session, request.symbol, as_of=as_of, window_days=10)

        if not history:
            result = OrderResult(
                order_id=order_id,
                request=request,
                status=OrderStatus.REJECTED,
                rejected_reason=f"no point-in-time price data for '{request.symbol}' as of {as_of}",
            )
            self._orders[order_id] = result
            self._log(result)
            return result

        latest_price = history[-1][1]
        filled_price: float | None = None

        if request.order_type == OrderType.MARKET:
            filled_price = latest_price
        else:
            if request.limit_price is None:
                result = OrderResult(
                    order_id=order_id,
                    request=request,
                    status=OrderStatus.REJECTED,
                    rejected_reason="limit order requires limit_price",
                )
                self._orders[order_id] = result
                self._log(result)
                return result

            marketable = (
                request.side == OrderSide.BUY and request.limit_price >= latest_price
            ) or (request.side == OrderSide.SELL and request.limit_price <= latest_price)
            if marketable:
                filled_price = latest_price

        if filled_price is not None:
            result = OrderResult(
                order_id=order_id,
                request=request,
                status=OrderStatus.FILLED,
                filled_quantity=request.quantity,
                filled_price=filled_price,
                filled_at=dt.datetime.now(dt.UTC),
            )
        else:
            result = OrderResult(order_id=order_id, request=request, status=OrderStatus.PENDING)

        self._orders[order_id] = result
        self._log(result)
        return result

    def get_order(self, order_id: str) -> OrderResult | None:
        return self._orders.get(order_id)

    def cancel_order(self, order_id: str) -> bool:
        result = self._orders.get(order_id)
        if result is None or result.status != OrderStatus.PENDING:
            return False
        result.status = OrderStatus.CANCELLED
        self._log(result)
        return True

    def _log(self, result: OrderResult) -> None:
        log_event(
            self._session,
            event_type="paper_order",
            entity_type="order",
            entity_id=result.order_id,
            payload={
                "symbol": result.request.symbol,
                "side": result.request.side.value,
                "quantity": result.request.quantity,
                "order_type": result.request.order_type.value,
                "status": result.status.value,
                "filled_price": result.filled_price,
                "trade_id": result.request.trade_id,
            },
            actor="paper_broker",
        )
