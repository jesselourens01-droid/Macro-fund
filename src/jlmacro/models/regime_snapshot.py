"""Persisted output of the macro regime engine (src/jlmacro/models/regime/).

One row per (country, as_of, model_version): the four category scores/buckets, the
classified regime label, and a confidence measure. Persisting this (rather than only
computing it on demand) is what lets duration/previous-regime/transition-probability
queries work without recomputing history from raw MacroDataPoint every time, and is
what the dashboard's regime matrix and future attribution-by-regime reporting read
from.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Enum, Float, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from jlmacro.database.base import Base
from jlmacro.models.enums import RegimeLabel


class RegimeSnapshot(Base):
    __tablename__ = "regime_snapshots"
    __table_args__ = (
        UniqueConstraint("country", "as_of", "model_version", name="uq_regime_snapshot_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    country: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)

    growth_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    growth_bucket: Mapped[int | None] = mapped_column(nullable=True)
    inflation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    inflation_bucket: Mapped[int | None] = mapped_column(nullable=True)
    monetary_policy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    monetary_policy_bucket: Mapped[int | None] = mapped_column(nullable=True)
    financial_conditions_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    financial_conditions_bucket: Mapped[int | None] = mapped_column(nullable=True)

    regime_label: Mapped[RegimeLabel] = mapped_column(Enum(RegimeLabel), nullable=False)
    regime_confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # Bumped whenever the classification logic/config changes meaningfully, so old and
    # new snapshots for the same (country, as_of) can coexist rather than collide -
    # see the platform-wide "unique IDs for models" auditability requirement.
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<RegimeSnapshot {self.country} {self.as_of} {self.regime_label}>"
