"""Shared mixin for point-in-time (PIT) records.

The whole point of this mixin is to prevent look-ahead bias: every fact in the system
carries both the date it is "about" (effective_date) and the date it actually became
knowable (release_date / revision_date / ingestion_timestamp). Any query that wants
"what did we know as of date X" must filter on release_date/ingestion_timestamp <= X,
never assume the latest row in the table was known at the time it describes.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column


class PointInTimeMixin:
    """Common PIT bookkeeping columns for market and macro observations."""

    source: Mapped[str] = mapped_column(String(64), nullable=False)

    # The date/period this observation describes (e.g. the trading day for a price bar,
    # or the reference month/quarter for a macro indicator).
    effective_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)

    # When this observation was first published by the source. Null when unknown
    # (e.g. synthetic data, or a provider that doesn't expose it).
    release_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    # When *this particular row* (a specific vintage/revision of the value) was
    # published. Equal to release_date for a first release.
    revision_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    # When our system ingested/stored this row - always known, always set by us.
    ingestion_timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
