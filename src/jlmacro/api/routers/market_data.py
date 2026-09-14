"""Market data endpoints.

as_of is accepted on every read (defaulting to "now") as a discipline: even though
Phase 1's synthetic prices never get revised in practice, the query shape must be
"what was known as of this timestamp" from day one so later phases (backtesting,
research) never accidentally read data that wasn't yet knowable at a given date.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import MarketDataPointOut
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/{symbol}", response_model=list[MarketDataPointOut])
def get_market_data(
    symbol: str,
    start: dt.date | None = None,
    end: dt.date | None = None,
    as_of: dt.datetime | None = Query(
        default=None, description="Point-in-time cutoff; defaults to now"
    ),
    limit: int = Query(default=500, le=5000),
    db: Session = Depends(get_db),
) -> list[MarketDataPoint]:
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol}' not found")

    cutoff = as_of or dt.datetime.now(dt.UTC)
    stmt = (
        select(MarketDataPoint)
        .where(MarketDataPoint.instrument_id == instrument.id)
        .where(MarketDataPoint.ingestion_timestamp <= cutoff)
    )
    if start is not None:
        stmt = stmt.where(MarketDataPoint.effective_date >= start)
    if end is not None:
        stmt = stmt.where(MarketDataPoint.effective_date <= end)

    stmt = stmt.order_by(MarketDataPoint.timestamp.desc()).limit(limit)
    return list(db.scalars(stmt))
