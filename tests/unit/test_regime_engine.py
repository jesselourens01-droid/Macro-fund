from __future__ import annotations

import calendar
import datetime as dt

import pytest

from jlmacro.models.enums import Frequency, MacroCategory, RegimeLabel
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.regime.engine import (
    CategoryScore,
    _bucket,
    classify_regime,
    compute_and_persist_snapshot,
    compute_category_score,
    estimate_transition_matrix,
    regime_status,
)
from jlmacro.models.regime_snapshot import RegimeSnapshot


def _month_end(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def _insert(
    db_session, country: str, indicator_code: str, effective_date: dt.date, value: float
) -> None:
    db_session.add(
        MacroDataPoint(
            country=country,
            indicator_code=indicator_code,
            category=MacroCategory.GROWTH,
            frequency=Frequency.MONTHLY,
            value=value,
            original_value=value,
            source="TEST",
            effective_date=effective_date,
            release_date=effective_date,
            revision_date=effective_date,
        )
    )
    db_session.flush()


# --- bucket thresholds -------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (-3.0, -2),
        (-1.6, -2),
        (-1.4, -1),
        (-0.6, -1),
        (-0.4, 0),
        (0.4, 0),
        (0.6, 1),
        (1.4, 1),
        (1.6, 2),
        (3.0, 2),
    ],
)
def test_bucket_thresholds(score, expected):
    assert _bucket(score) == expected


# --- category score aggregation (invert sign, country allow-list) ------------------


def test_compute_category_score_averages_indicators(db_session):
    # PMI_MFG and PMI_SERVICES are both "growth" indicators with no invert flag.
    for i in range(1, 13):
        _insert(db_session, "US", "PMI_MFG", _month_end(2024, i), 50.0)
        _insert(db_session, "US", "PMI_SERVICES", _month_end(2024, i), 50.0)
    _insert(db_session, "US", "PMI_MFG", _month_end(2025, 1), 60.0)
    _insert(db_session, "US", "PMI_SERVICES", _month_end(2025, 1), 60.0)

    result = compute_category_score(
        db_session, "US", MacroCategory.GROWTH, as_of=_month_end(2025, 1)
    )
    assert result.score is not None
    assert result.score > 0
    assert result.bucket is not None


def test_compute_category_score_applies_invert_flag(db_session):
    # CREDIT_SPREAD_HY is configured with invert: true (wider spread = tighter
    # conditions), so a *high* raw spread must lower the financial_conditions score.
    for i in range(1, 13):
        _insert(db_session, "US", "CREDIT_SPREAD_HY", _month_end(2024, i), 400.0)
    _insert(db_session, "US", "CREDIT_SPREAD_HY", _month_end(2025, 1), 900.0)  # spread blows out

    result = compute_category_score(
        db_session, "US", MacroCategory.FINANCIAL_CONDITIONS, as_of=_month_end(2025, 1)
    )
    assert result.score is not None
    assert result.score < 0  # wider spread -> tighter -> negative financial conditions score


def test_compute_category_score_none_when_no_data(db_session):
    result = compute_category_score(
        db_session, "ZZ", MacroCategory.GROWTH, as_of=_month_end(2025, 1)
    )
    assert result.score is None
    assert result.bucket is None


def test_compute_category_score_respects_country_allowlist(db_session):
    # PCE is configured with countries: [US] only.
    for i in range(1, 13):
        _insert(db_session, "AU", "PCE", _month_end(2024, i), 2.0)
    result = compute_category_score(
        db_session, "AU", MacroCategory.INFLATION, as_of=_month_end(2024, 12)
    )
    assert result.score is None  # PCE excluded for AU, and no other AU inflation data seeded


# --- regime classification decision tree -------------------------------------------


def _score(bucket: int | None, momentum: float = 0.0) -> CategoryScore:
    score = float(bucket) if bucket is not None else None
    return CategoryScore(
        category=MacroCategory.GROWTH, score=score, bucket=bucket, momentum=momentum
    )


def test_classify_regime_goldilocks():
    label, _ = classify_regime(_score(1), _score(-1), _score(0), _score(0))
    assert label == RegimeLabel.GOLDILOCKS


def test_classify_regime_reflation():
    label, _ = classify_regime(_score(1), _score(1), _score(0), _score(0))
    assert label == RegimeLabel.REFLATION


def test_classify_regime_stagflation():
    label, _ = classify_regime(_score(-1), _score(1), _score(0), _score(0))
    assert label == RegimeLabel.STAGFLATION


def test_classify_regime_deflation():
    label, _ = classify_regime(_score(-1), _score(-1), _score(0), _score(0))
    assert label == RegimeLabel.DEFLATION


def test_classify_regime_recovery_overrides_deflation_quadrant():
    # growth_bucket <= 0, inflation_bucket <= 0 would normally be DEFLATION, but
    # positive growth momentum (a trough turning up) should classify as RECOVERY.
    label, _ = classify_regime(_score(0, momentum=1.0), _score(-1), _score(0), _score(0))
    assert label == RegimeLabel.RECOVERY


def test_classify_regime_late_cycle_overrides_reflation_quadrant():
    # growth_bucket >= 1, inflation_bucket >= 1 would normally be REFLATION, but
    # decelerating growth momentum with tight monetary policy should be LATE_CYCLE.
    label, _ = classify_regime(_score(1, momentum=-1.0), _score(1), _score(1), _score(0))
    assert label == RegimeLabel.LATE_CYCLE


def test_classify_regime_risk_off_overrides_quadrant():
    label, _ = classify_regime(_score(1), _score(-1), _score(0), _score(-1))
    assert label == RegimeLabel.RISK_OFF


def test_classify_regime_liquidity_crisis_overrides_risk_off():
    label, _ = classify_regime(_score(-1), _score(-1), _score(0), _score(-2))
    assert label == RegimeLabel.LIQUIDITY_CRISIS


def test_classify_regime_confidence_between_zero_and_one():
    label, confidence = classify_regime(_score(1), _score(-1), _score(0), _score(0))
    assert label == RegimeLabel.GOLDILOCKS
    assert 0.0 <= confidence <= 1.0


# --- persistence, status, transitions ----------------------------------------------


def test_compute_and_persist_snapshot_is_idempotent(db_session):
    for i in range(1, 13):
        _insert(db_session, "US", "PMI_MFG", _month_end(2024, i), 50.0)

    first = compute_and_persist_snapshot(db_session, "US", as_of=_month_end(2025, 1))
    second = compute_and_persist_snapshot(db_session, "US", as_of=_month_end(2025, 1))
    assert first.id == second.id

    count = (
        db_session.query(RegimeSnapshot).filter_by(country="US", as_of=_month_end(2025, 1)).count()
    )
    assert count == 1


def _insert_snapshot(db_session, country: str, as_of: dt.date, regime: RegimeLabel) -> None:
    db_session.add(
        RegimeSnapshot(
            country=country,
            as_of=as_of,
            regime_label=regime,
            regime_confidence=0.5,
        )
    )
    db_session.flush()


def test_regime_status_tracks_duration_and_previous(db_session):
    _insert_snapshot(db_session, "XX", _month_end(2024, 1), RegimeLabel.REFLATION)
    _insert_snapshot(db_session, "XX", _month_end(2024, 2), RegimeLabel.GOLDILOCKS)
    _insert_snapshot(db_session, "XX", _month_end(2024, 3), RegimeLabel.GOLDILOCKS)
    _insert_snapshot(db_session, "XX", _month_end(2024, 4), RegimeLabel.GOLDILOCKS)

    status = regime_status(db_session, "XX")
    assert status is not None
    assert status.current == RegimeLabel.GOLDILOCKS
    assert status.previous == RegimeLabel.REFLATION
    assert status.duration_periods == 3


def test_regime_status_none_without_history(db_session):
    assert regime_status(db_session, "NOPE") is None


def test_estimate_transition_matrix(db_session):
    _insert_snapshot(db_session, "YY", _month_end(2024, 1), RegimeLabel.GOLDILOCKS)
    _insert_snapshot(db_session, "YY", _month_end(2024, 2), RegimeLabel.GOLDILOCKS)
    _insert_snapshot(db_session, "YY", _month_end(2024, 3), RegimeLabel.RISK_OFF)
    _insert_snapshot(db_session, "YY", _month_end(2024, 4), RegimeLabel.GOLDILOCKS)

    matrix = estimate_transition_matrix(db_session, "YY")
    # From GOLDILOCKS: 1 transition to GOLDILOCKS, 1 to RISK_OFF -> 50/50.
    assert matrix["goldilocks"]["goldilocks"] == pytest.approx(0.5)
    assert matrix["goldilocks"]["risk_off"] == pytest.approx(0.5)
    # From RISK_OFF: always back to GOLDILOCKS in this history.
    assert matrix["risk_off"]["goldilocks"] == pytest.approx(1.0)
