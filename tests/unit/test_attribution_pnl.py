from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.attribution.pnl import compute_pnl_attribution
from jlmacro.models.enums import AssetClass, Frequency, TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.portfolio import Portfolio
from jlmacro.trades.lifecycle import create_trade_idea, transition
from jlmacro.trades.review import close_trade

_TODAY = dt.datetime.now(dt.UTC).date()


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


def _seed_two_trades(db_session):
    portfolio = Portfolio(name="Attribution Test Fund")
    equity = Instrument(
        symbol="ATTREQ", name="Attr Equity", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    rate = Instrument(
        symbol="ATTRATE", name="Attr Rate", asset_class=AssetClass.RATE, currency="USD"
    )
    db_session.add_all([portfolio, equity, rate])
    db_session.flush()

    _insert_bar(db_session, equity, _TODAY, 110.0)  # +10%, still open

    winner = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=equity.id,
        direction=TradeDirection.LONG,
        thesis="winner",
        entry_price=100.0,
        position_size=100_000.0,
    )
    transition(db_session, winner, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, winner, TradeStatus.OPEN, actor="jesse")

    loser = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=rate.id,
        direction=TradeDirection.SHORT,
        thesis="loser",
        entry_price=5.0,
        position_size=50_000.0,
    )
    transition(db_session, loser, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, loser, TradeStatus.OPEN, actor="jesse")
    close_trade(db_session, loser, exit_price=5.5, actor="jesse")  # short loses 10%

    return portfolio


def test_pnl_attribution_by_symbol(db_session):
    portfolio = _seed_two_trades(db_session)

    result = compute_pnl_attribution(db_session, portfolio.id, as_of=_TODAY, group_by="symbol")

    assert result["ATTREQ"] == pytest.approx(10_000.0)
    assert result["ATTRATE"] == pytest.approx(-5_000.0)


def test_pnl_attribution_by_asset_class(db_session):
    portfolio = _seed_two_trades(db_session)

    result = compute_pnl_attribution(db_session, portfolio.id, as_of=_TODAY, group_by="asset_class")

    assert result["equity_index"] == pytest.approx(10_000.0)
    assert result["rate"] == pytest.approx(-5_000.0)


def test_pnl_attribution_by_direction(db_session):
    portfolio = _seed_two_trades(db_session)

    result = compute_pnl_attribution(db_session, portfolio.id, as_of=_TODAY, group_by="direction")

    assert result["long"] == pytest.approx(10_000.0)
    assert result["short"] == pytest.approx(-5_000.0)


def test_pnl_attribution_excludes_trades_with_zero_pnl(db_session):
    portfolio = Portfolio(name="Attribution Zero Fund")
    instrument = Instrument(
        symbol="ATTRZERO", name="Attr Zero", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add_all([portfolio, instrument])
    db_session.flush()

    create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="never opened",
        entry_price=100.0,
        position_size=100_000.0,
    )

    result = compute_pnl_attribution(db_session, portfolio.id, as_of=_TODAY, group_by="symbol")
    assert result == {}
