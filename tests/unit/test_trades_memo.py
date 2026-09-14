from __future__ import annotations

import pytest

from jlmacro.models.enums import AssetClass, TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Portfolio
from jlmacro.trades.lifecycle import create_trade_idea, transition
from jlmacro.trades.memo import generate_investment_memo


def _seed(db_session):
    portfolio = Portfolio(name="Test Fund Memo")
    instrument = Instrument(
        symbol="MEMOTEST", name="Memo Test Instrument", asset_class=AssetClass.RATE, currency="USD"
    )
    db_session.add_all([portfolio, instrument])
    db_session.flush()
    return portfolio, instrument


def test_generate_investment_memo_reflects_the_trade_row_exactly(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.SHORT,
        thesis="Rates are going up.",
        macro_score=60.0,
        trend_score=75.0,
        composite_score=68.0,
        entry_price=4.5,
        target_price=5.0,
        stop_price=4.2,
        portfolio_risk_pct=0.005,
        position_size=200_000.0,
        regime_at_entry="reflation",
    )

    memo = generate_investment_memo(db_session, trade)

    assert memo.trade_id == trade.trade_id
    assert memo.symbol == "MEMOTEST"
    assert memo.direction == "short"
    assert memo.status == "idea"
    assert memo.thesis == "Rates are going up."
    assert memo.scores["macro_score"] == 60.0
    assert memo.scores["valuation_score"] is None
    assert memo.regime_at_entry == "reflation"
    assert memo.entry_price == 4.5
    assert memo.pm_approved_by is None


def test_memo_markdown_includes_key_sections(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="Test thesis for markdown rendering.",
        composite_score=80.0,
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")

    memo = generate_investment_memo(db_session, trade)
    markdown = memo.to_markdown()

    assert "# Investment Memo: MEMOTEST (LONG)" in markdown
    assert "Test thesis for markdown rendering." in markdown
    assert "Composite" in markdown
    assert "Approved by: jesse" in markdown


def test_generate_investment_memo_raises_for_missing_instrument(db_session):
    from jlmacro.models.portfolio import Trade

    # Deliberately not added/flushed to the session - a persisted Trade can never
    # reference a nonexistent instrument (the FK constraint on trades.instrument_id
    # enforces that), so this only tests the function's own defensive lookup.
    trade = Trade(
        portfolio_id=1,
        instrument_id=999_999,
        direction=TradeDirection.LONG,
    )

    with pytest.raises(ValueError, match="not found"):
        generate_investment_memo(db_session, trade)
