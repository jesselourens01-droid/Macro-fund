"""Macro data endpoints.

as_of implements the point-in-time discipline: it filters on the *vintage* date
(revision_date, falling back to release_date when a row has no revision_date), never on
release_date alone. release_date stays constant across every revision of a given
effective_date - filtering on it would let a later revision leak into an as_of query for
a date before that revision existed, i.e. exactly the look-ahead bias this platform
exists to prevent.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import MacroDataPointOut
from jlmacro.models.macro_data import MacroDataPoint

router = APIRouter(prefix="/macro-data", tags=["macro-data"])


@router.get("/{country}/{indicator_code}", response_model=list[MacroDataPointOut])
def get_macro_data(
    country: str,
    indicator_code: str,
    start: dt.date | None = None,
    end: dt.date | None = None,
    as_of: dt.date | None = Query(default=None, description="Point-in-time cutoff on vintage date"),
    limit: int = Query(default=500, le=5000),
    db: Session = Depends(get_db),
) -> list[MacroDataPoint]:
    stmt = (
        select(MacroDataPoint)
        .where(MacroDataPoint.country == country.upper())
        .where(MacroDataPoint.indicator_code == indicator_code.upper())
    )
    if as_of is not None:
        vintage_date = func.coalesce(MacroDataPoint.revision_date, MacroDataPoint.release_date)
        stmt = stmt.where(vintage_date <= as_of)
    if start is not None:
        stmt = stmt.where(MacroDataPoint.effective_date >= start)
    if end is not None:
        stmt = stmt.where(MacroDataPoint.effective_date <= end)

    stmt = stmt.order_by(
        MacroDataPoint.effective_date.desc(), MacroDataPoint.revision_date.desc()
    ).limit(limit)
    return list(db.scalars(stmt))
