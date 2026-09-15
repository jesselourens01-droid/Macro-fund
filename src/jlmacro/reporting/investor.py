"""Investor-facing reporting queries and portable export helpers.

The dashboard deliberately consumes these functions instead of embedding SQL in the
presentation layer.  That keeps every number reproducible and makes the same curated
datasets available to future PDF reports, client portals and downstream integrations.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jlmacro.models.audit import AuditLogEntry
from jlmacro.models.enums import TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.portfolio import Portfolio, Trade
from jlmacro.models.regime_snapshot import RegimeSnapshot


@dataclass(frozen=True)
class DataQualitySnapshot:
    """Small, serialisable control record for the investor reporting layer."""

    active_instruments: int
    instruments_with_prices: int
    price_coverage_pct: float
    market_rows: int
    macro_rows: int
    regime_snapshots: int
    audit_events: int
    latest_market_date: dt.date | None
    latest_macro_date: dt.date | None
    latest_ingestion_at: dt.datetime | None
    market_sources: int
    macro_sources: int


def market_pulse(
    session: Session,
    *,
    as_of: dt.date | None = None,
    lookback_sessions: int = 20,
) -> pd.DataFrame:
    """Return one decision-useful, point-in-time market row per active instrument."""

    instruments = session.scalars(
        select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol)
    ).all()
    rows: list[dict[str, object]] = []
    required = max(2, lookback_sessions + 1)

    for instrument in instruments:
        statement = select(MarketDataPoint).where(
            MarketDataPoint.instrument_id == instrument.id
        )
        if as_of is not None:
            statement = statement.where(MarketDataPoint.effective_date <= as_of)
        observations = session.scalars(
            statement.order_by(MarketDataPoint.timestamp.desc()).limit(required)
        ).all()
        if not observations:
            continue

        closes = pd.Series([point.close for point in reversed(observations)], dtype=float)
        returns = closes.pct_change().dropna()
        latest = observations[0]
        previous = observations[1].close if len(observations) > 1 else None
        lookback = observations[-1].close if len(observations) > lookback_sessions else None
        rows.append(
            {
                "symbol": instrument.symbol,
                "name": instrument.name,
                "asset_class": getattr(instrument.asset_class, "value", instrument.asset_class),
                "country": instrument.country or "Global",
                "currency": instrument.currency,
                "last": latest.close,
                "change_1d": latest.close / previous - 1.0 if previous else None,
                "return_20d": latest.close / lookback - 1.0 if lookback else None,
                "realised_vol_20d": (
                    float(returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 else None
                ),
                "as_of": latest.effective_date,
                "source": latest.source,
            }
        )

    return pd.DataFrame(rows)


def data_quality_snapshot(session: Session) -> DataQualitySnapshot:
    """Summarise coverage, lineage and recency without inventing a quality score."""

    active_instruments = (
        session.scalar(
            select(func.count()).select_from(Instrument).where(Instrument.is_active.is_(True))
        )
        or 0
    )
    instruments_with_prices = (
        session.scalar(select(func.count(func.distinct(MarketDataPoint.instrument_id)))) or 0
    )
    latest_market = session.execute(
        select(
            func.max(MarketDataPoint.effective_date),
            func.max(MarketDataPoint.ingestion_timestamp),
        )
    ).one()
    latest_macro = session.execute(
        select(
            func.max(MacroDataPoint.effective_date),
            func.max(MacroDataPoint.ingestion_timestamp),
        )
    ).one()
    latest_ingestion = max(
        (value for value in (latest_market[1], latest_macro[1]) if value is not None),
        default=None,
    )

    return DataQualitySnapshot(
        active_instruments=active_instruments,
        instruments_with_prices=instruments_with_prices,
        price_coverage_pct=(
            instruments_with_prices / active_instruments if active_instruments else 0.0
        ),
        market_rows=session.scalar(select(func.count()).select_from(MarketDataPoint)) or 0,
        macro_rows=session.scalar(select(func.count()).select_from(MacroDataPoint)) or 0,
        regime_snapshots=session.scalar(select(func.count()).select_from(RegimeSnapshot)) or 0,
        audit_events=session.scalar(select(func.count()).select_from(AuditLogEntry)) or 0,
        latest_market_date=latest_market[0],
        latest_macro_date=latest_macro[0],
        latest_ingestion_at=latest_ingestion,
        market_sources=session.scalar(select(func.count(func.distinct(MarketDataPoint.source))))
        or 0,
        macro_sources=session.scalar(select(func.count(func.distinct(MacroDataPoint.source)))) or 0,
    )


def portfolio_operating_summary(session: Session, portfolio_id: int) -> dict[str, object]:
    """Operational exposure and workflow totals for a single portfolio."""

    portfolio = session.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise ValueError(f"Portfolio {portfolio_id} does not exist")

    trades = session.scalars(select(Trade).where(Trade.portfolio_id == portfolio_id)).all()
    live_statuses = {TradeStatus.OPEN, TradeStatus.REDUCE}
    live_trades = [trade for trade in trades if trade.status in live_statuses]
    gross_notional = sum(abs(trade.position_size or 0.0) for trade in live_trades)
    net_notional = sum(
        (1.0 if trade.direction == TradeDirection.LONG else -1.0)
        * abs(trade.position_size or 0.0)
        for trade in live_trades
    )
    status_counts = {status.value: 0 for status in TradeStatus}
    for trade in trades:
        status_counts[trade.status.value] += 1

    return {
        "portfolio_id": portfolio.id,
        "portfolio_name": portfolio.name,
        "base_currency": portfolio.base_currency,
        "trades_total": len(trades),
        "live_trades": len(live_trades),
        "gross_notional": gross_notional,
        "net_notional": net_notional,
        "status_counts": status_counts,
    }


def recent_audit_activity(session: Session, *, limit: int = 50) -> pd.DataFrame:
    """Return the immutable control trail in a presentation-safe table."""

    entries = session.scalars(
        select(AuditLogEntry).order_by(AuditLogEntry.created_at.desc()).limit(limit)
    ).all()
    return pd.DataFrame(
        [
            {
                "timestamp": entry.created_at,
                "event": entry.event_type,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "actor": entry.actor,
            }
            for entry in entries
        ]
    )


def build_data_room_export(
    *,
    market: pd.DataFrame,
    regimes: pd.DataFrame,
    instruments: pd.DataFrame,
    audit: pd.DataFrame,
    quality: DataQualitySnapshot,
    generated_at: dt.datetime,
) -> bytes:
    """Create a portable ZIP with CSV datasets plus a machine-readable manifest."""

    manifest = {
        "report": "JL Global Macro investor data room export",
        "generated_at": generated_at.isoformat(),
        "data_classification": "research",
        "live_trading_enabled": False,
        "quality": asdict(quality),
        "files": ["market_pulse.csv", "regimes.csv", "instruments.csv", "audit_trail.csv"],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, frame in (
            ("market_pulse.csv", market),
            ("regimes.csv", regimes),
            ("instruments.csv", instruments),
            ("audit_trail.csv", audit),
        ):
            archive.writestr(filename, frame.to_csv(index=False))
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
    return buffer.getvalue()
