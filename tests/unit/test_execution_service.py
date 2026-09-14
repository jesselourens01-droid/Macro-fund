from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.execution.base import OrderStatus
from jlmacro.execution.paper_broker import PaperBroker
from jlmacro.execution.service import (
    close_trade_via_broker,
    direction_to_side,
    open_trade_via_broker,
)
from jlmacro.models.enums import AssetClass, Frequency, TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.portfolio import Portfolio
from jlmacro.trades.lifecycle import create_trade_idea, transition

_TODAY = dt.datetime.now(dt.UTC).date()


def _seed(db_session):
    portfolio = Portfolio(name="Exec Service Test Fund")
    instrument = Instrument(
        symbol="EXECSVC", name="Exec Svc Test", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add_all([portfolio, instrument])
    db_session.flush()
    db_session.add(
        MarketDataPoint(
            instrument_id=instrument.id,
            timestamp=dt.datetime.combine(_TODAY, dt.time(21, 0), tzinfo=dt.UTC),
            frequency=Frequency.DAILY,
            close=100.0,
            source="TEST",
            effective_date=_TODAY,
            release_date=_TODAY,
            revision_date=_TODAY,
        )
    )
    db_session.flush()
    return portfolio, instrument


@pytest.mark.parametrize(
    ("direction", "closing", "expected"),
    [
        (TradeDirection.LONG, False, "buy"),
        (TradeDirection.LONG, True, "sell"),
        (TradeDirection.SHORT, False, "sell"),
        (TradeDirection.SHORT, True, "buy"),
    ],
)
def test_direction_to_side(direction, closing, expected):
    assert direction_to_side(direction, closing=closing).value == expected


def test_open_trade_via_broker_fills_and_transitions_to_open(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    broker = PaperBroker(db_session)

    result = open_trade_via_broker(
        db_session, broker, trade, quantity=10, as_of=_TODAY, actor="jesse"
    )

    assert result.status == OrderStatus.FILLED
    assert trade.status == TradeStatus.OPEN
    assert trade.entry_price == pytest.approx(100.0)


def test_open_trade_via_broker_requires_approved_status(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
    )
    broker = PaperBroker(db_session)

    with pytest.raises(ValueError, match="APPROVED"):
        open_trade_via_broker(db_session, broker, trade, quantity=10, as_of=_TODAY, actor="jesse")


def test_close_trade_via_broker_fills_and_closes(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    broker = PaperBroker(db_session)
    open_trade_via_broker(db_session, broker, trade, quantity=10, as_of=_TODAY, actor="jesse")

    result = close_trade_via_broker(
        db_session, broker, trade, quantity=10, as_of=_TODAY, actor="jesse"
    )

    assert result.status == OrderStatus.FILLED
    assert trade.status == TradeStatus.CLOSED
    assert trade.extra["exit_price"] == pytest.approx(100.0)


def test_close_trade_via_broker_requires_open_or_reduce_status(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
    )
    broker = PaperBroker(db_session)

    with pytest.raises(ValueError, match="OPEN or REDUCE"):
        close_trade_via_broker(db_session, broker, trade, quantity=10, as_of=_TODAY, actor="jesse")


def test_rejected_order_leaves_trade_status_unchanged(db_session):
    portfolio = Portfolio(name="Exec Service Reject Fund")
    instrument = Instrument(
        symbol="EXECREJ", name="Exec Reject", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add_all([portfolio, instrument])
    db_session.flush()  # deliberately no price data seeded

    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    broker = PaperBroker(db_session)

    result = open_trade_via_broker(
        db_session, broker, trade, quantity=10, as_of=_TODAY, actor="jesse"
    )

    assert result.status == OrderStatus.REJECTED
    assert trade.status == TradeStatus.APPROVED  # unchanged
