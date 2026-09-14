"""Catalyst engine.

This platform does not yet have a real forward economic calendar (with analyst
consensus estimates) or an events/elections/earnings-dates data source (Phase 2+
work - see config/signals.yaml's top comment). Rather than leave this unimplemented,
two honestly-documented proxies stand in for it:

- **Upcoming catalysts** are *projected*, not scheduled: for each indicator tracked
  for a country, the historical cadence between releases (and the typical lag from
  the period it covers to its publication) is used to project when the next release
  is likely due. This is a reasonable approximation for indicators with a regular
  cadence (most macro releases are monthly/quarterly on a fairly fixed lag) but is
  not an authoritative calendar - it can't know about a specific announced date, a
  postponement, or a one-off event (an election, a special central bank meeting).
- **Surprise** is self-referential: since there is no consensus-estimate data source,
  "surprise" here means how far the latest known value sits from the indicator's own
  recent history (reusing jlmacro.models.regime.scoring.rolling_zscore), not a
  Bloomberg-style actual-vs-consensus surprise.

Distinguishes near-term catalysts (this module) from the structural thesis (the
regime/valuation/trend scores, which are already inherently longer-horizon) per the
platform spec.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.regime.scoring import rolling_zscore


@dataclass
class CatalystEvent:
    country: str
    indicator_code: str
    projected_effective_date: dt.date
    projected_release_date: dt.date


@dataclass
class CatalystResult:
    score: float  # 0-100, 50 = neutral baseline; driven by recent-surprise direction
    upcoming_events: list[CatalystEvent] = field(default_factory=list)
    average_surprise: float | None = None


def _indicator_codes_for_country(country: str) -> list[str]:
    config = load_yaml_config("macro_indicators")
    codes = []
    for items in config.get("indicators", {}).values():
        for item in items:
            allowed_countries = item.get("countries")
            if allowed_countries is not None and country not in allowed_countries:
                continue
            codes.append(item["code"])
    return codes


def _known_periods(
    session: Session, country: str, indicator_code: str, as_of: dt.date
) -> list[tuple[dt.date, dt.date]]:
    """[(effective_date, release_date)] for vintages already knowable by `as_of`, one
    (the latest known) per period, sorted by effective_date.
    """
    stmt = select(MacroDataPoint).where(
        MacroDataPoint.country == country,
        MacroDataPoint.indicator_code == indicator_code,
        MacroDataPoint.effective_date <= as_of,
    )
    rows = session.scalars(stmt).all()

    latest: dict[dt.date, MacroDataPoint] = {}
    for row in rows:
        vintage = row.revision_date or row.release_date or row.effective_date
        if vintage > as_of:
            continue
        existing = latest.get(row.effective_date)
        if existing is None:
            latest[row.effective_date] = row
            continue
        existing_vintage = (
            existing.revision_date or existing.release_date or existing.effective_date
        )
        if existing_vintage < vintage:
            latest[row.effective_date] = row

    return sorted(
        (effective_date, row.release_date or effective_date)
        for effective_date, row in latest.items()
    )


def _project_next_release(periods: list[tuple[dt.date, dt.date]]) -> tuple[dt.date, dt.date] | None:
    if len(periods) < 2:
        return None
    effective_gaps = [(periods[i][0] - periods[i - 1][0]).days for i in range(1, len(periods))]
    release_lags = [(release - effective).days for effective, release in periods]

    next_effective = periods[-1][0] + dt.timedelta(days=round(statistics.median(effective_gaps)))
    next_release = next_effective + dt.timedelta(days=round(statistics.median(release_lags)))
    return next_effective, next_release


def upcoming_catalysts(
    session: Session, country: str, *, as_of: dt.date, window_days: int | None = None
) -> list[CatalystEvent]:
    """Projected releases due in [as_of, as_of + window_days] - see module docstring
    for why these are projections, not a scheduled calendar.
    """
    config = load_yaml_config("signals")["catalyst"]
    window_days = window_days if window_days is not None else config["upcoming_window_days"]

    events: list[CatalystEvent] = []
    for indicator_code in _indicator_codes_for_country(country):
        periods = _known_periods(session, country, indicator_code, as_of)
        projected = _project_next_release(periods)
        if projected is None:
            continue
        next_effective, next_release = projected
        if as_of <= next_release <= as_of + dt.timedelta(days=window_days):
            events.append(
                CatalystEvent(
                    country=country,
                    indicator_code=indicator_code,
                    projected_effective_date=next_effective,
                    projected_release_date=next_release,
                )
            )
    return sorted(events, key=lambda event: event.projected_release_date)


def indicator_surprise(
    session: Session, country: str, indicator_code: str, *, as_of: dt.date
) -> float | None:
    """How many standard deviations the latest known value sits from the indicator's
    own recent history - see module docstring for why this stands in for a true
    actual-vs-consensus surprise.
    """
    return rolling_zscore(session, country, indicator_code, as_of=as_of)


def catalyst_score(session: Session, country: str, *, as_of: dt.date) -> CatalystResult:
    config = load_yaml_config("signals")["catalyst"]
    events = upcoming_catalysts(
        session, country, as_of=as_of, window_days=config["upcoming_window_days"]
    )

    surprises = [
        z
        for code in _indicator_codes_for_country(country)
        if (z := indicator_surprise(session, country, code, as_of=as_of)) is not None
    ]
    average_surprise = sum(surprises) / len(surprises) if surprises else None

    if average_surprise is None:
        return CatalystResult(score=50.0, upcoming_events=events, average_surprise=None)

    # An imminent projected catalyst amplifies how much recent surprise momentum
    # moves the score, since it raises the odds that momentum matters again soon.
    imminent_events = min(len(events), config["max_upcoming_events_counted"])
    amplification = 1.0 + imminent_events * (config["upcoming_event_weight"] / 100.0)
    score = 50.0 + config["surprise_weight"] * amplification * math.tanh(average_surprise / 2.0)
    score = max(0.0, min(100.0, score))

    return CatalystResult(score=score, upcoming_events=events, average_surprise=average_surprise)
