"""Point-in-time market price observations (equity indices, rates, FX, commodities).

Backed by a TimescaleDB hypertable in production (see alembic migration) for efficient
time-range queries; behaves as a normal Postgres table otherwise (e.g. in unit tests
against plain Postgres/SQLite).
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jlmacro.database.base import Base
from jlmacro.models.enums import Frequency
from jlmacro.models.mixins import PointInTimeMixin

if TYPE_CHECKING:
    from jlmacro.models.instrument import Instrument


class MarketDataPoint(Base, PointInTimeMixin):
    __tablename__ = "market_data_points"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "timestamp",
            "frequency",
            "source",
            name="uq_market_data_point_identity",
        ),
        Index("ix_market_data_instrument_timestamp", "instrument_id", "timestamp"),
    )

    # Composite primary key (id, timestamp): TimescaleDB requires every unique/primary
    # key constraint on a hypertable to include the partitioning column, so `timestamp`
    # must be part of the PK rather than a plain indexed column.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    frequency: Mapped[Frequency] = mapped_column(Enum(Frequency), nullable=False)

    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Populated only when a price is later corrected by the source; original_value
    # preserves what was known first so backtests can reproduce point-in-time reality.
    original_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    revised_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    instrument: Mapped[Instrument] = relationship(back_populates="market_data_points")

    def __repr__(self) -> str:
        return f"<MarketDataPoint instrument_id={self.instrument_id} {self.timestamp} close={self.close}>"
