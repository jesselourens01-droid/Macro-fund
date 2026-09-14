from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.models.enums import AssetClass, Frequency, TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.portfolio import Portfolio
from jlmacro.nav.engine import (
    compute_nav,
    compute_portfolio_pnl,
    compute_trade_pnl,
    current_drawdown,
    drawdown_series,
    high_water_mark_series,
    nav_history,
)
from jlmacro.trades.lifecycle import create_trade_idea, transition
from jlmacro.trades.review import close_trade

_TODAY = dt.datetime.now(dt.UTC).date()


def _seed(db_session):
    portfolio = Portfolio(name="NAV Test Fund")
    instrument = Instrument(
        symbol="NAVTEST", name="NAV Test", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add_all([portfolio, instrument])
    db_session.flush()
    return portfolio, instrument


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


def test_trade_not_yet_open_contributes_zero_pnl(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
        entry_price=100.0,
        position_size=100_000.0,
    )
    assert compute_trade_pnl(db_session, trade, as_of=_TODAY) == 0.0


def test_open_long_trade_marks_to_market_using_latest_pit_close(db_session):
    portfolio, instrument = _seed(db_session)
    _insert_bar(db_session, instrument, _TODAY, 110.0)  # +10% since entry

    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
        entry_price=100.0,
        position_size=100_000.0,
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, trade, TradeStatus.OPEN, actor="jesse")

    pnl = compute_trade_pnl(db_session, trade, as_of=_TODAY)
    assert pnl == pytest.approx(10_000.0)


def test_open_short_trade_sign_is_inverted(db_session):
    portfolio, instrument = _seed(db_session)
    _insert_bar(db_session, instrument, _TODAY, 90.0)  # -10% since entry -> short wins

    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.SHORT,
        thesis="t",
        entry_price=100.0,
        position_size=100_000.0,
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, trade, TradeStatus.OPEN, actor="jesse")

    pnl = compute_trade_pnl(db_session, trade, as_of=_TODAY)
    assert pnl == pytest.approx(10_000.0)


def test_closed_trade_uses_recorded_exit_price_not_market_data(db_session):
    portfolio, instrument = _seed(db_session)
    # Market keeps moving after the trade closes - closed P&L must not follow it.
    _insert_bar(db_session, instrument, _TODAY, 999.0)

    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
        entry_price=100.0,
        position_size=100_000.0,
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, trade, TradeStatus.OPEN, actor="jesse")
    close_trade(db_session, trade, exit_price=120.0, actor="jesse")

    pnl = compute_trade_pnl(db_session, trade, as_of=_TODAY)
    assert pnl == pytest.approx(20_000.0)


def test_compute_portfolio_pnl_sums_across_trades(db_session):
    portfolio, instrument = _seed(db_session)
    instrument2 = Instrument(
        symbol="NAVTEST2", name="NAV Test 2", asset_class=AssetClass.RATE, currency="USD"
    )
    db_session.add(instrument2)
    db_session.flush()
    _insert_bar(db_session, instrument, _TODAY, 110.0)

    t1 = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t1",
        entry_price=100.0,
        position_size=100_000.0,
    )
    transition(db_session, t1, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, t1, TradeStatus.OPEN, actor="jesse")

    t2 = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument2.id,
        direction=TradeDirection.LONG,
        thesis="t2",
        entry_price=5.0,
        position_size=50_000.0,
    )
    transition(db_session, t2, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, t2, TradeStatus.OPEN, actor="jesse")
    close_trade(db_session, t2, exit_price=5.5, actor="jesse")  # +10%

    total = compute_portfolio_pnl(db_session, portfolio.id, as_of=_TODAY)
    assert total == pytest.approx(10_000.0 + 5_000.0)


def test_compute_nav_adds_pnl_to_starting_capital(db_session):
    portfolio, instrument = _seed(db_session)
    _insert_bar(db_session, instrument, _TODAY, 110.0)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
        entry_price=100.0,
        position_size=100_000.0,
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, trade, TradeStatus.OPEN, actor="jesse")

    nav = compute_nav(db_session, portfolio.id, as_of=_TODAY, starting_capital=1_000_000.0)
    assert nav == pytest.approx(1_010_000.0)


def test_high_water_mark_and_drawdown_series(db_session):
    import pandas as pd

    nav_series = pd.Series([100.0, 110.0, 90.0, 95.0, 120.0])
    hwm = high_water_mark_series(nav_series)
    assert list(hwm) == [100.0, 110.0, 110.0, 110.0, 120.0]

    dd = drawdown_series(nav_series)
    assert dd.iloc[2] == pytest.approx(90.0 / 110.0 - 1.0)
    assert dd.iloc[4] == pytest.approx(0.0)


def test_current_drawdown_reflects_a_losing_open_position(db_session):
    portfolio, instrument = _seed(db_session)
    start = _TODAY - dt.timedelta(days=10)
    _insert_bar(db_session, instrument, start, 100.0)
    _insert_bar(db_session, instrument, _TODAY, 80.0)  # -20% since entry

    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="t",
        entry_price=100.0,
        position_size=1_000_000.0,
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, trade, TradeStatus.OPEN, actor="jesse")

    dd = current_drawdown(
        db_session,
        portfolio.id,
        as_of=_TODAY,
        start=start,
        starting_capital=1_000_000.0,
        frequency_days=1,
    )
    assert dd < 0.0


def test_nav_history_covers_the_full_range_inclusive(db_session):
    portfolio, _instrument = _seed(db_session)
    start = _TODAY - dt.timedelta(days=5)
    series = nav_history(
        db_session,
        portfolio.id,
        start=start,
        end=_TODAY,
        starting_capital=1_000.0,
        frequency_days=2,
    )
    assert series.index[0] == start
    assert series.index[-1] == _TODAY
