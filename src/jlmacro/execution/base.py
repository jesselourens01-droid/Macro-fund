"""Broker abstraction: `BaseBroker` defines the interface every execution venue
(paper, and eventually real brokers) must implement; nothing outside this package
talks to a broker any other way, so swapping paper for a real venue later never
touches calling code, only which concrete broker gets constructed.

Live trading is disabled by default (`jlmacro.config.Settings.jlmacro_live_trading_enabled`)
and there is no real broker implementation yet - `PaperBroker` (`.paper_broker`) is
the only concrete broker in this codebase. `.safeguards` is the pre-trade gate any
future live broker must pass through before it can submit anything.
"""

from __future__ import annotations

import abc
import datetime as dt
import enum
import uuid
from dataclasses import dataclass, field


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, enum.Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    trade_id: str | None = None  # links back to jlmacro.models.portfolio.Trade, if any


@dataclass
class OrderResult:
    order_id: str
    request: OrderRequest
    status: OrderStatus
    filled_quantity: float = 0.0
    filled_price: float | None = None
    rejected_reason: str | None = None
    submitted_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    filled_at: dt.datetime | None = None


class BaseBroker(abc.ABC):
    name: str

    @abc.abstractmethod
    def submit_order(self, request: OrderRequest, *, as_of: dt.date) -> OrderResult: ...

    @abc.abstractmethod
    def get_order(self, order_id: str) -> OrderResult | None: ...

    @abc.abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...


def new_order_id() -> str:
    return str(uuid.uuid4())
