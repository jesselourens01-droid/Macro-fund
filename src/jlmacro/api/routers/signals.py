"""Quantitative signal engine endpoints (jlmacro.models.signals, Phase 4)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import InvestmentScoreOut
from jlmacro.models.enums import AssetClass
from jlmacro.models.instrument import Instrument
from jlmacro.models.signals import InvestmentScore, compute_investment_score

router = APIRouter(prefix="/signals", tags=["signals"])


def _to_out(score: InvestmentScore) -> InvestmentScoreOut:
    return InvestmentScoreOut(
        instrument_symbol=score.instrument_symbol,
        as_of=score.as_of,
        macro_score=score.macro_score,
        valuation_score=score.valuation_score,
        trend_score=score.trend_score,
        positioning_score=score.positioning_score,
        catalyst_score=score.catalyst_score,
        composite_score=score.composite_score,
        action=score.action,
        suggested_risk_units=score.suggested_risk_units,
        detail=score.detail,
    )


@router.get("", response_model=list[InvestmentScoreOut])
def list_investment_scores(
    asset_class: AssetClass | None = None,
    as_of: dt.date | None = Query(
        default=None, description="Point-in-time cutoff; defaults to today"
    ),
    db: Session = Depends(get_db),
) -> list[InvestmentScoreOut]:
    """Investment scores for the active instrument universe, ranked by composite
    score descending - the platform spec's "highest-ranking opportunities" view.
    """
    as_of = as_of or dt.datetime.now(dt.UTC).date()
    stmt = select(Instrument).where(Instrument.is_active.is_(True))
    if asset_class is not None:
        stmt = stmt.where(Instrument.asset_class == asset_class)
    instruments = db.scalars(stmt.order_by(Instrument.symbol)).all()

    scores = [
        compute_investment_score(db, instrument.symbol, as_of=as_of) for instrument in instruments
    ]
    scores.sort(
        key=lambda s: s.composite_score if s.composite_score is not None else -1, reverse=True
    )
    return [_to_out(s) for s in scores]


@router.get("/{symbol}", response_model=InvestmentScoreOut)
def get_investment_score(
    symbol: str,
    as_of: dt.date | None = Query(
        default=None, description="Point-in-time cutoff; defaults to today"
    ),
    db: Session = Depends(get_db),
) -> InvestmentScoreOut:
    as_of = as_of or dt.datetime.now(dt.UTC).date()
    try:
        score = compute_investment_score(db, symbol.upper(), as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_out(score)
