"""Point-in-time close-price history for the signal engines.

Mirrors jlmacro.models.regime.scoring's discipline for macro data: for each
effective_date, use only the vintage of that bar (revision_date, falling back to
release_date) that was actually knowable as of `as_of`. MarketDataPoint carries the
same PointInTimeMixin fields as MacroDataPoint, so a price correction issued after the
fact can't leak into an earlier as-of query here either - today's synthetic/FRED-style
providers rarely revise a price, but the discipline costs nothing and a future
provider that does correct historical bars is covered for free.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint


def point_in_time_closes(
    session: Session, symbol: str, *, as_of: dt.date, window_days: int
) -> list[tuple[dt.date, float]]:
    """Return [(effective_date, close)] sorted by effective_date, using only the
    vintage of each day's bar known by `as_of`, within a trailing `window_days` window.
    """
    window_start = as_of - dt.timedelta(days=window_days)
    stmt = (
        select(
            MarketDataPoint.effective_date,
            MarketDataPoint.close,
            MarketDataPoint.revision_date,
            MarketDataPoint.release_date,
        )
        .join(Instrument, Instrument.id == MarketDataPoint.instrument_id)
        .where(Instrument.symbol == symbol)
        .where(MarketDataPoint.effective_date >= window_start)
        .where(MarketDataPoint.effective_date <= as_of)
    )
    rows = session.execute(stmt).all()

    latest_by_day: dict[dt.date, tuple[dt.date, float]] = {}
    for effective_date, close, revision_date, release_date in rows:
        vintage = revision_date or release_date or effective_date
        if vintage > as_of:
            continue
        existing = latest_by_day.get(effective_date)
        if existing is None or existing[0] < vintage:
            latest_by_day[effective_date] = (vintage, close)

    return sorted((day, vintage_close[1]) for day, vintage_close in latest_by_day.items())
