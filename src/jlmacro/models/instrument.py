"""The configurable asset universe. Rows are seeded from config/assets.yaml
(see scripts/generate_synthetic_data.py) rather than hard-coded in application logic.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jlmacro.database.base import Base
from jlmacro.models.enums import AssetClass

if TYPE_CHECKING:
    from jlmacro.models.market_data import MarketDataPoint


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("symbol", name="uq_instruments_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(Enum(AssetClass), nullable=False)

    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    calendar: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Free-form extra attributes (e.g. tenor_years for rates, base/quote for FX, unit for
    # commodities) so the schema doesn't need to change every time a new asset class's
    # metadata differs.
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    market_data_points: Mapped[list[MarketDataPoint]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Instrument {self.symbol} ({self.asset_class})>"
