from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.execution.base import OrderRequest, OrderSide, OrderStatus, OrderType
from jlmacro.execution.paper_broker import PaperBroker
from jlmacro.models.audit import AuditLogEntry
from jlmacro.models.enums import AssetClass, Frequency
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint

_TODAY = dt.datetime.now(dt.UTC).date()


def _seed_instrument(db_session, symbol: str) -> Instrument:
    instrument = Instrument(
        symbol=symbol, name=symbol, asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add(instrument)
    db_session.flush()
    return instrument


def _insert_bar(db_session, instrument, day: dt.date, close: float) -> None:
    db_session.add(
        MarketDataPoint(
            instrument_id=instrument.id,
            timestamp=dt.datetime.combine(day, dt.time(21, 0), tzinfo=dt.UTC),
            frequency=Frequency.DAILY,
            close=close,
            source="TEST",
            effective_date=day,
            release_date=day,
            revision_date=day,
        )
    )


def test_market_order_fills_immediately_at_latest_pit_close(db_session):
    instrument = _seed_instrument(db_session, "PBTEST1")
    _insert_bar(db_session, instrument, _TODAY, 105.0)
    broker = PaperBroker(db_session)

    result = broker.submit_order(
        OrderRequest(symbol="PBTEST1", side=OrderSide.BUY, quantity=100), as_of=_TODAY
    )

    assert result.status == OrderStatus.FILLED
    assert result.filled_price == pytest.approx(105.0)
    assert result.filled_quantity == 100


def test_order_for_symbol_with_no_price_history_is_rejected(db_session):
    _seed_instrument(db_session, "PBTEST2")
    broker = PaperBroker(db_session)

    result = broker.submit_order(
        OrderRequest(symbol="PBTEST2", side=OrderSide.BUY, quantity=100), as_of=_TODAY
    )

    assert result.status == OrderStatus.REJECTED
    assert "no point-in-time price data" in result.rejected_reason


def test_marketable_buy_limit_fills_at_prevailing_price(db_session):
    instrument = _seed_instrument(db_session, "PBTEST3")
    _insert_bar(db_session, instrument, _TODAY, 100.0)
    broker = PaperBroker(db_session)

    result = broker.submit_order(
        OrderRequest(
            symbol="PBTEST3",
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.LIMIT,
            limit_price=105.0,  # willing to pay more than the current price
        ),
        as_of=_TODAY,
    )

    assert result.status == OrderStatus.FILLED
    assert result.filled_price == pytest.approx(100.0)


def test_non_marketable_sell_limit_stays_pending(db_session):
    instrument = _seed_instrument(db_session, "PBTEST4")
    _insert_bar(db_session, instrument, _TODAY, 100.0)
    broker = PaperBroker(db_session)

    result = broker.submit_order(
        OrderRequest(
            symbol="PBTEST4",
            side=OrderSide.SELL,
            quantity=10,
            order_type=OrderType.LIMIT,
            limit_price=110.0,  # wants more than the current price - not marketable
        ),
        as_of=_TODAY,
    )

    assert result.status == OrderStatus.PENDING
    assert result.filled_price is None


def test_limit_order_without_limit_price_is_rejected(db_session):
    instrument = _seed_instrument(db_session, "PBTEST5")
    _insert_bar(db_session, instrument, _TODAY, 100.0)
    broker = PaperBroker(db_session)

    result = broker.submit_order(
        OrderRequest(symbol="PBTEST5", side=OrderSide.BUY, quantity=10, order_type=OrderType.LIMIT),
        as_of=_TODAY,
    )

    assert result.status == OrderStatus.REJECTED


def test_cancel_order_only_succeeds_while_pending(db_session):
    instrument = _seed_instrument(db_session, "PBTEST6")
    _insert_bar(db_session, instrument, _TODAY, 100.0)
    broker = PaperBroker(db_session)

    pending = broker.submit_order(
        OrderRequest(
            symbol="PBTEST6",
            side=OrderSide.SELL,
            quantity=10,
            order_type=OrderType.LIMIT,
            limit_price=110.0,
        ),
        as_of=_TODAY,
    )
    filled = broker.submit_order(
        OrderRequest(symbol="PBTEST6", side=OrderSide.BUY, quantity=10), as_of=_TODAY
    )

    assert broker.cancel_order(pending.order_id) is True
    assert broker.get_order(pending.order_id).status == OrderStatus.CANCELLED
    assert broker.cancel_order(filled.order_id) is False


def test_every_order_is_logged_to_the_audit_trail(db_session):
    instrument = _seed_instrument(db_session, "PBTEST7")
    _insert_bar(db_session, instrument, _TODAY, 100.0)
    broker = PaperBroker(db_session)

    result = broker.submit_order(
        OrderRequest(symbol="PBTEST7", side=OrderSide.BUY, quantity=10), as_of=_TODAY
    )

    entries = (
        db_session.query(AuditLogEntry)
        .filter_by(entity_id=result.order_id, event_type="paper_order")
        .all()
    )
    assert len(entries) == 1
    assert entries[0].actor == "paper_broker"
