"""Point-in-time macroeconomic indicator observations.

Each (country, indicator_code, effective_date, revision_date) tuple is a distinct row -
revisions are new rows, never in-place updates - so a query "what was known as of date X"
is simply a filter on release_date <= X, giving a true historical vintage rather than a
restated series.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, Enum, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from jlmacro.database.base import Base
from jlmacro.models.enums import Frequency, MacroCategory
from jlmacro.models.mixins import PointInTimeMixin


class MacroDataPoint(Base, PointInTimeMixin):
    __tablename__ = "macro_data_points"
    __table_args__ = (
        UniqueConstraint(
            "country",
            "indicator_code",
            "effective_date",
            "revision_date",
            "source",
            name="uq_macro_data_point_identity",
        ),
        Index(
            "ix_macro_country_indicator_effective", "country", "indicator_code", "effective_date"
        ),
    )

    # Composite primary key (id, effective_date): TimescaleDB requires every
    # unique/primary key constraint on a hypertable to include the partitioning column.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    effective_date: Mapped[dt.date] = mapped_column(Date, primary_key=True, nullable=False)
    country: Mapped[str] = mapped_column(String(8), nullable=False)
    indicator_code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[MacroCategory] = mapped_column(Enum(MacroCategory), nullable=False)
    frequency: Mapped[Frequency] = mapped_column(Enum(Frequency), nullable=False)

    # Best-known value for this row's vintage (== original_value on first release).
    value: Mapped[float] = mapped_column(Float, nullable=False)
    original_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    revised_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<MacroDataPoint {self.country}/{self.indicator_code} "
            f"eff={self.effective_date} value={self.value}>"
        )
