"""Trade lifecycle endpoints (jlmacro.trades, Phase 8): create a trade idea, move it
through its lifecycle, generate its investment memo, and (once closed) its post-trade
review. A minimal portfolios endpoint is included too, since every trade needs a
`portfolio_id` and none existed yet.

Every state change here is audited (`jlmacro.utils.audit.log_event`, via
`jlmacro.trades.lifecycle.transition`) and validated against the trade lifecycle's
state graph - an illegal jump (e.g. straight from `idea` to `open`) is rejected, and
approving a trade requires a named human actor, never `system`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import (
    CloseTradeOrderRequest,
    InvestmentMemoOut,
    OpenTradeOrderRequest,
    OrderOut,
    PortfolioCreateRequest,
    PortfolioOut,
    PostTradeReviewOut,
    TradeCloseRequest,
    TradeIdeaCreateRequest,
    TradeOut,
    TradeTransitionRequest,
)
from jlmacro.execution.base import OrderResult
from jlmacro.execution.paper_broker import PaperBroker
from jlmacro.execution.service import close_trade_via_broker, open_trade_via_broker
from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Portfolio, Trade
from jlmacro.trades.lifecycle import InvalidTransitionError, create_trade_idea, transition
from jlmacro.trades.memo import generate_investment_memo
from jlmacro.trades.review import close_trade, generate_post_trade_review

router = APIRouter(tags=["trades"])


@router.post("/portfolios", response_model=PortfolioOut)
def create_portfolio(request: PortfolioCreateRequest, db: Session = Depends(get_db)) -> Portfolio:
    existing = db.scalar(select(Portfolio).where(Portfolio.name == request.name))
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"portfolio '{request.name}' already exists")
    portfolio = Portfolio(name=request.name, base_currency=request.base_currency)
    db.add(portfolio)
    db.flush()
    return portfolio


@router.get("/portfolios", response_model=list[PortfolioOut])
def list_portfolios(db: Session = Depends(get_db)) -> list[Portfolio]:
    return list(db.scalars(select(Portfolio).order_by(Portfolio.name)))


def _get_trade_or_404(db: Session, trade_id: str) -> Trade:
    trade = db.scalar(select(Trade).where(Trade.trade_id == trade_id))
    if trade is None:
        raise HTTPException(status_code=404, detail=f"trade '{trade_id}' not found")
    return trade


@router.post("/trades", response_model=TradeOut)
def post_trade_idea(request: TradeIdeaCreateRequest, db: Session = Depends(get_db)) -> Trade:
    portfolio = db.get(Portfolio, request.portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"portfolio {request.portfolio_id} not found")
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == request.symbol.upper()))
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"instrument '{request.symbol}' not found")

    return create_trade_idea(
        db,
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        direction=request.direction,
        thesis=request.thesis,
        macro_score=request.macro_score,
        valuation_score=request.valuation_score,
        trend_score=request.trend_score,
        positioning_score=request.positioning_score,
        catalyst_score=request.catalyst_score,
        composite_score=request.composite_score,
        entry_price=request.entry_price,
        target_price=request.target_price,
        stop_price=request.stop_price,
        portfolio_risk_pct=request.portfolio_risk_pct,
        position_size=request.position_size,
        regime_at_entry=request.regime_at_entry,
        actor=request.actor,
    )


@router.get("/trades", response_model=list[TradeOut])
def list_trades(
    portfolio_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[Trade]:
    stmt = select(Trade)
    if portfolio_id is not None:
        stmt = stmt.where(Trade.portfolio_id == portfolio_id)
    if status is not None:
        stmt = stmt.where(Trade.status == status)
    return list(db.scalars(stmt.order_by(Trade.created_at.desc())))


@router.get("/trades/{trade_id}", response_model=TradeOut)
def get_trade(trade_id: str, db: Session = Depends(get_db)) -> Trade:
    return _get_trade_or_404(db, trade_id)


@router.post("/trades/{trade_id}/transition", response_model=TradeOut)
def post_trade_transition(
    trade_id: str, request: TradeTransitionRequest, db: Session = Depends(get_db)
) -> Trade:
    trade = _get_trade_or_404(db, trade_id)
    try:
        return transition(db, trade, request.new_status, actor=request.actor, reason=request.reason)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/trades/{trade_id}/close", response_model=TradeOut)
def post_trade_close(
    trade_id: str, request: TradeCloseRequest, db: Session = Depends(get_db)
) -> Trade:
    trade = _get_trade_or_404(db, trade_id)
    try:
        return close_trade(
            db, trade, exit_price=request.exit_price, actor=request.actor, reason=request.reason
        )
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/trades/{trade_id}/memo", response_model=InvestmentMemoOut)
def get_trade_memo(trade_id: str, db: Session = Depends(get_db)) -> InvestmentMemoOut:
    trade = _get_trade_or_404(db, trade_id)
    memo = generate_investment_memo(db, trade)
    return InvestmentMemoOut(
        trade_id=memo.trade_id,
        symbol=memo.symbol,
        instrument_name=memo.instrument_name,
        direction=memo.direction,
        status=memo.status,
        thesis=memo.thesis,
        scores=memo.scores,
        regime_at_entry=memo.regime_at_entry,
        entry_price=memo.entry_price,
        target_price=memo.target_price,
        stop_price=memo.stop_price,
        portfolio_risk_pct=memo.portfolio_risk_pct,
        position_size=memo.position_size,
        pm_approved_by=memo.pm_approved_by,
        pm_approved_at=memo.pm_approved_at,
        generated_at=memo.generated_at,
        markdown=memo.to_markdown(),
    )


@router.get("/trades/{trade_id}/review", response_model=PostTradeReviewOut)
def get_trade_review(trade_id: str, db: Session = Depends(get_db)) -> PostTradeReviewOut:
    trade = _get_trade_or_404(db, trade_id)
    try:
        review = generate_post_trade_review(db, trade)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PostTradeReviewOut(
        trade_id=review.trade_id,
        symbol=review.symbol,
        direction=review.direction,
        entry_price=review.entry_price,
        exit_price=review.exit_price,
        realised_return_pct=review.realised_return_pct,
        composite_score_at_entry=review.composite_score_at_entry,
        thesis_direction_correct=review.thesis_direction_correct,
        notes=review.notes,
    )


def _order_to_out(result: OrderResult) -> OrderOut:
    return OrderOut(
        order_id=result.order_id,
        symbol=result.request.symbol,
        side=result.request.side.value,
        quantity=result.request.quantity,
        order_type=result.request.order_type.value,
        status=result.status.value,
        filled_quantity=result.filled_quantity,
        filled_price=result.filled_price,
        rejected_reason=result.rejected_reason,
        trade_id=result.request.trade_id,
        submitted_at=result.submitted_at,
        filled_at=result.filled_at,
    )


@router.post("/trades/{trade_id}/open-order", response_model=OrderOut)
def post_open_trade_order(
    trade_id: str, request: OpenTradeOrderRequest, db: Session = Depends(get_db)
) -> OrderOut:
    """Submits a market order via the paper broker (the only broker this codebase
    has - live trading is disabled by default) to open an APPROVED trade. Only an
    actual fill advances the trade's status; a rejected order leaves it untouched.
    """
    trade = _get_trade_or_404(db, trade_id)
    broker = PaperBroker(db)
    try:
        result = open_trade_via_broker(
            db, broker, trade, quantity=request.quantity, as_of=request.as_of, actor=request.actor
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _order_to_out(result)


@router.post("/trades/{trade_id}/close-order", response_model=OrderOut)
def post_close_trade_order(
    trade_id: str, request: CloseTradeOrderRequest, db: Session = Depends(get_db)
) -> OrderOut:
    trade = _get_trade_or_404(db, trade_id)
    broker = PaperBroker(db)
    try:
        result = close_trade_via_broker(
            db, broker, trade, quantity=request.quantity, as_of=request.as_of, actor=request.actor
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _order_to_out(result)
