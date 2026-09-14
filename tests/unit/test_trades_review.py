from __future__ import annotations

import pytest

from jlmacro.models.enums import AssetClass, TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Portfolio
from jlmacro.trades.lifecycle import create_trade_idea, transition
from jlmacro.trades.review import close_trade, generate_post_trade_review


def _seed(db_session):
    portfolio = Portfolio(name="Test Fund Review")
    instrument = Instrument(
        symbol="REVTEST", name="Review Test", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add_all([portfolio, instrument])
    db_session.flush()
    return portfolio, instrument


def _open_trade(db_session, portfolio, instrument, *, direction, entry_price, composite_score=70.0):
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=direction,
        thesis="Test thesis",
        composite_score=composite_score,
        entry_price=entry_price,
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, trade, TradeStatus.OPEN, actor="jesse")
    return trade


def test_close_trade_records_exit_price_and_transitions_to_closed(db_session):
    portfolio, instrument = _seed(db_session)
    trade = _open_trade(
        db_session, portfolio, instrument, direction=TradeDirection.LONG, entry_price=100.0
    )

    close_trade(db_session, trade, exit_price=110.0, actor="jesse", reason="target hit")

    assert trade.status == TradeStatus.CLOSED
    assert trade.extra["exit_price"] == 110.0
    assert "closed_at" in trade.extra
    assert trade.extra["lifecycle_history"][-1]["reason"] == "target hit"


def test_post_trade_review_long_winning_trade_is_direction_correct(db_session):
    portfolio, instrument = _seed(db_session)
    trade = _open_trade(
        db_session, portfolio, instrument, direction=TradeDirection.LONG, entry_price=100.0
    )
    close_trade(db_session, trade, exit_price=110.0, actor="jesse")

    review = generate_post_trade_review(db_session, trade)

    assert review.realised_return_pct == pytest.approx(0.10)
    assert review.thesis_direction_correct is True


def test_post_trade_review_short_winning_trade_has_positive_realised_return(db_session):
    portfolio, instrument = _seed(db_session)
    trade = _open_trade(
        db_session, portfolio, instrument, direction=TradeDirection.SHORT, entry_price=100.0
    )
    close_trade(db_session, trade, exit_price=90.0, actor="jesse")

    review = generate_post_trade_review(db_session, trade)

    assert review.realised_return_pct == pytest.approx(0.10)
    assert review.thesis_direction_correct is True


def test_post_trade_review_losing_trade_is_direction_incorrect(db_session):
    portfolio, instrument = _seed(db_session)
    trade = _open_trade(
        db_session, portfolio, instrument, direction=TradeDirection.LONG, entry_price=100.0
    )
    close_trade(db_session, trade, exit_price=90.0, actor="jesse")

    review = generate_post_trade_review(db_session, trade)

    assert review.realised_return_pct == pytest.approx(-0.10)
    assert review.thesis_direction_correct is False


def test_post_trade_review_requires_closed_trade(db_session):
    portfolio, instrument = _seed(db_session)
    trade = _open_trade(
        db_session, portfolio, instrument, direction=TradeDirection.LONG, entry_price=100.0
    )

    with pytest.raises(ValueError, match="CLOSED"):
        generate_post_trade_review(db_session, trade)


def test_post_trade_review_handles_missing_entry_price_gracefully(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="No entry price recorded",
    )
    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, trade, TradeStatus.OPEN, actor="jesse")
    close_trade(db_session, trade, exit_price=110.0, actor="jesse")

    review = generate_post_trade_review(db_session, trade)

    assert review.realised_return_pct is None
    assert review.thesis_direction_correct is None
    assert "not computable" in review.notes
