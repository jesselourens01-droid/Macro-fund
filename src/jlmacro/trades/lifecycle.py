"""Trade lifecycle state machine over `jlmacro.models.portfolio.Trade` /
`TradeStatus`: IDEA -> WATCHLIST/APPROVED -> OPEN -> REDUCE -> CLOSED, with
INVALIDATED reachable from any non-terminal state.

Every transition is validated against `ALLOWED_TRANSITIONS` (an illegal jump, e.g.
IDEA straight to OPEN, raises rather than silently happening) and logged through
`jlmacro.utils.audit.log_event` - the platform's single sanctioned audit path - plus
appended to the trade's own `extra["lifecycle_history"]` so the row carries its full
history without a join. Moving into `APPROVED` specifically requires an `actor` (the
platform spec's human-approval gate before a trade can be sized/opened); nothing here
can approve itself.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from jlmacro.models.enums import TradeDirection, TradeStatus
from jlmacro.models.portfolio import Trade
from jlmacro.utils.audit import log_event

ALLOWED_TRANSITIONS: dict[TradeStatus, set[TradeStatus]] = {
    TradeStatus.IDEA: {TradeStatus.WATCHLIST, TradeStatus.APPROVED, TradeStatus.INVALIDATED},
    TradeStatus.WATCHLIST: {TradeStatus.APPROVED, TradeStatus.INVALIDATED},
    TradeStatus.APPROVED: {TradeStatus.OPEN, TradeStatus.INVALIDATED},
    TradeStatus.OPEN: {TradeStatus.REDUCE, TradeStatus.CLOSED},
    TradeStatus.REDUCE: {TradeStatus.OPEN, TradeStatus.CLOSED},
    TradeStatus.CLOSED: set(),
    TradeStatus.INVALIDATED: set(),
}


class InvalidTransitionError(ValueError):
    pass


def create_trade_idea(
    session: Session,
    *,
    portfolio_id: int,
    instrument_id: int,
    direction: TradeDirection,
    thesis: str,
    macro_score: float | None = None,
    valuation_score: float | None = None,
    trend_score: float | None = None,
    positioning_score: float | None = None,
    catalyst_score: float | None = None,
    composite_score: float | None = None,
    entry_price: float | None = None,
    target_price: float | None = None,
    stop_price: float | None = None,
    portfolio_risk_pct: float | None = None,
    position_size: float | None = None,
    regime_at_entry: str | None = None,
    actor: str = "system",
) -> Trade:
    """A trade always starts life as an unapproved `IDEA` - nothing about this
    function can put a trade straight into `APPROVED` or `OPEN`; those require an
    explicit, separately-logged `transition` call.
    """
    trade = Trade(
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        direction=direction,
        status=TradeStatus.IDEA,
        thesis=thesis,
        macro_score=macro_score,
        valuation_score=valuation_score,
        trend_score=trend_score,
        positioning_score=positioning_score,
        catalyst_score=catalyst_score,
        composite_score=composite_score,
        entry_price=entry_price,
        target_price=target_price,
        stop_price=stop_price,
        portfolio_risk_pct=portfolio_risk_pct,
        position_size=position_size,
        regime_at_entry=regime_at_entry,
        extra={"lifecycle_history": []},
    )
    session.add(trade)
    session.flush()

    log_event(
        session,
        event_type="trade_idea_created",
        entity_type="trade",
        entity_id=trade.trade_id,
        payload={"instrument_id": instrument_id, "direction": direction.value, "thesis": thesis},
        actor=actor,
    )
    return trade


def transition(
    session: Session,
    trade: Trade,
    new_status: TradeStatus,
    *,
    actor: str,
    reason: str | None = None,
) -> Trade:
    current_status = trade.status
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise InvalidTransitionError(
            f"cannot transition trade {trade.trade_id} from {current_status.value} "
            f"to {new_status.value}; allowed: {sorted(s.value for s in allowed)}"
        )

    if new_status == TradeStatus.APPROVED:
        if not actor or actor == "system":
            raise InvalidTransitionError(
                "approving a trade requires a named human actor, not 'system' - "
                "per the platform spec's human-approval gate"
            )
        trade.pm_approved_by = actor
        trade.pm_approved_at = dt.datetime.now(dt.UTC)

    history_entry = {
        "from": current_status.value,
        "to": new_status.value,
        "at": dt.datetime.now(dt.UTC).isoformat(),
        "actor": actor,
        "reason": reason,
    }
    extra = dict(trade.extra or {})
    lifecycle_history = list(extra.get("lifecycle_history", []))
    lifecycle_history.append(history_entry)
    extra["lifecycle_history"] = lifecycle_history
    trade.extra = extra
    trade.status = new_status
    session.flush()

    log_event(
        session,
        event_type="trade_status_changed",
        entity_type="trade",
        entity_id=trade.trade_id,
        payload=history_entry,
        actor=actor,
    )
    return trade
