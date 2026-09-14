from __future__ import annotations

import pytest

from jlmacro.models.audit import AuditLogEntry
from jlmacro.models.enums import AssetClass, TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Portfolio
from jlmacro.trades.lifecycle import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    create_trade_idea,
    transition,
)


def _seed(db_session):
    portfolio = Portfolio(name="Test Fund LC")
    instrument = Instrument(
        symbol="LCTEST", name="LC Test", asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add_all([portfolio, instrument])
    db_session.flush()
    return portfolio, instrument


def test_create_trade_idea_starts_in_idea_status_and_logs_audit_event(db_session):
    portfolio, instrument = _seed(db_session)

    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="Test thesis",
        composite_score=70.0,
    )

    assert trade.status == TradeStatus.IDEA
    assert trade.extra["lifecycle_history"] == []

    audit_entries = db_session.query(AuditLogEntry).filter_by(entity_id=trade.trade_id).all()
    assert any(e.event_type == "trade_idea_created" for e in audit_entries)


def test_illegal_transition_is_rejected(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="Test thesis",
    )

    with pytest.raises(InvalidTransitionError):
        transition(db_session, trade, TradeStatus.OPEN, actor="jesse")

    assert trade.status == TradeStatus.IDEA  # unchanged after a rejected attempt


def test_approval_requires_a_named_human_actor(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="Test thesis",
    )

    with pytest.raises(InvalidTransitionError, match="human actor"):
        transition(db_session, trade, TradeStatus.APPROVED, actor="system")

    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse.lourens")
    assert trade.status == TradeStatus.APPROVED
    assert trade.pm_approved_by == "jesse.lourens"
    assert trade.pm_approved_at is not None


def test_transition_appends_to_lifecycle_history_and_logs_audit_event(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.SHORT,
        thesis="Test thesis",
    )

    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse", reason="looks good")
    transition(db_session, trade, TradeStatus.OPEN, actor="jesse")

    history = trade.extra["lifecycle_history"]
    assert len(history) == 2
    assert history[0] == {
        "from": "idea",
        "to": "approved",
        "at": history[0]["at"],
        "actor": "jesse",
        "reason": "looks good",
    }
    assert history[1]["to"] == "open"

    audit_entries = (
        db_session.query(AuditLogEntry)
        .filter_by(entity_id=trade.trade_id, event_type="trade_status_changed")
        .all()
    )
    assert len(audit_entries) == 2


def test_full_lifecycle_idea_to_closed(db_session):
    portfolio, instrument = _seed(db_session)
    trade = create_trade_idea(
        db_session,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=TradeDirection.LONG,
        thesis="Test thesis",
    )

    transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")
    transition(db_session, trade, TradeStatus.OPEN, actor="jesse")
    transition(db_session, trade, TradeStatus.REDUCE, actor="jesse", reason="trimming risk")
    transition(db_session, trade, TradeStatus.CLOSED, actor="jesse")

    assert trade.status == TradeStatus.CLOSED
    assert ALLOWED_TRANSITIONS[TradeStatus.CLOSED] == set()  # terminal


def test_invalidated_is_reachable_from_idea_and_watchlist_and_approved(db_session):
    portfolio, instrument = _seed(db_session)

    for start_status in (TradeStatus.IDEA, TradeStatus.WATCHLIST, TradeStatus.APPROVED):
        trade = create_trade_idea(
            db_session,
            portfolio_id=portfolio.id,
            instrument_id=instrument.id,
            direction=TradeDirection.LONG,
            thesis="Test thesis",
        )
        if start_status == TradeStatus.WATCHLIST:
            transition(db_session, trade, TradeStatus.WATCHLIST, actor="jesse")
        elif start_status == TradeStatus.APPROVED:
            transition(db_session, trade, TradeStatus.APPROVED, actor="jesse")

        transition(db_session, trade, TradeStatus.INVALIDATED, actor="jesse")
        assert trade.status == TradeStatus.INVALIDATED
