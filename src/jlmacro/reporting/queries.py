"""Read-only query helpers shared by the dashboard (and usable by future reporting jobs).

Kept in src/ rather than in dashboards/ so the dashboard and the API are both thin
presentation layers over the same production data-access logic, per the project's
"keep research/notebooks separate from production logic" rule.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jlmacro.models.audit import AuditLogEntry
from jlmacro.models.instrument import Instrument
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.regime_snapshot import RegimeSnapshot


def list_instruments(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(
            Instrument.symbol,
            Instrument.name,
            Instrument.asset_class,
            Instrument.country,
            Instrument.currency,
        )
        .where(Instrument.is_active.is_(True))
        .order_by(Instrument.asset_class, Instrument.symbol)
    ).all()
    df = pd.DataFrame(rows, columns=["symbol", "name", "asset_class", "country", "currency"])
    if not df.empty:
        df["asset_class"] = df["asset_class"].map(lambda v: getattr(v, "value", v))
    return df


def market_data_history(
    session: Session, symbol: str, *, start: dt.date | None = None, end: dt.date | None = None
) -> pd.DataFrame:
    stmt = (
        select(
            MarketDataPoint.timestamp,
            MarketDataPoint.open,
            MarketDataPoint.high,
            MarketDataPoint.low,
            MarketDataPoint.close,
            MarketDataPoint.volume,
        )
        .join(Instrument, Instrument.id == MarketDataPoint.instrument_id)
        .where(Instrument.symbol == symbol)
    )
    if start is not None:
        stmt = stmt.where(MarketDataPoint.effective_date >= start)
    if end is not None:
        stmt = stmt.where(MarketDataPoint.effective_date <= end)
    stmt = stmt.order_by(MarketDataPoint.timestamp)

    rows = session.execute(stmt).all()
    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])


def macro_data_history(session: Session, country: str, indicator_code: str) -> pd.DataFrame:
    stmt = (
        select(
            MacroDataPoint.effective_date,
            MacroDataPoint.release_date,
            MacroDataPoint.revision_date,
            MacroDataPoint.value,
            MacroDataPoint.original_value,
            MacroDataPoint.revised_value,
        )
        .where(MacroDataPoint.country == country, MacroDataPoint.indicator_code == indicator_code)
        .order_by(MacroDataPoint.effective_date, MacroDataPoint.revision_date)
    )
    rows = session.execute(stmt).all()
    return pd.DataFrame(
        rows,
        columns=[
            "effective_date",
            "release_date",
            "revision_date",
            "value",
            "original_value",
            "revised_value",
        ],
    )


def regime_matrix(session: Session, countries: list[str]) -> pd.DataFrame:
    """Latest regime snapshot for each of the given countries - one row per country,
    missing countries simply absent (rather than a row of nulls) so the caller decides
    how to render "no data yet".
    """
    rows = []
    for country in countries:
        stmt = (
            select(RegimeSnapshot)
            .where(RegimeSnapshot.country == country)
            .order_by(RegimeSnapshot.as_of.desc())
            .limit(1)
        )
        snapshot = session.scalar(stmt)
        if snapshot is None:
            continue
        rows.append(
            {
                "country": country,
                "as_of": snapshot.as_of,
                "regime": snapshot.regime_label.value,
                "confidence": snapshot.regime_confidence,
                "growth": snapshot.growth_bucket,
                "inflation": snapshot.inflation_bucket,
                "monetary_policy": snapshot.monetary_policy_bucket,
                "financial_conditions": snapshot.financial_conditions_bucket,
            }
        )
    return pd.DataFrame(rows)


def regime_history(session: Session, country: str) -> pd.DataFrame:
    stmt = (
        select(RegimeSnapshot)
        .where(RegimeSnapshot.country == country)
        .order_by(RegimeSnapshot.as_of)
    )
    rows = session.scalars(stmt).all()
    return pd.DataFrame(
        [
            {
                "as_of": r.as_of,
                "regime": r.regime_label.value,
                "confidence": r.regime_confidence,
                "growth_score": r.growth_score,
                "inflation_score": r.inflation_score,
                "monetary_policy_score": r.monetary_policy_score,
                "financial_conditions_score": r.financial_conditions_score,
            }
            for r in rows
        ]
    )


def system_status(session: Session) -> dict[str, int]:
    return {
        "instruments": session.scalar(select(func.count()).select_from(Instrument)) or 0,
        "market_data_points": session.scalar(select(func.count()).select_from(MarketDataPoint))
        or 0,
        "macro_data_points": session.scalar(select(func.count()).select_from(MacroDataPoint)) or 0,
        "audit_log_entries": session.scalar(select(func.count()).select_from(AuditLogEntry)) or 0,
    }
