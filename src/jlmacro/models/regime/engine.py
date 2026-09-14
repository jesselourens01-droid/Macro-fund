"""Category score aggregation and regime classification.

Transparent, rule-based v1, per the platform spec's "transparent models before complex
models" principle - HMM/logistic/gradient-boosted regime classifiers are explicitly
future work (the spec's Phase 3 notes: "later add Hidden Markov Models, logistic
classification, gradient boosting, Bayesian regime estimation"). This module is the
part that gets superseded then; jlmacro.models.regime.scoring's point-in-time
discipline is not - any future classifier still has to consume causally-computed
features, not this decision tree.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.enums import MacroCategory, RegimeLabel
from jlmacro.models.regime.scoring import rolling_zscore, zscore_momentum
from jlmacro.models.regime_snapshot import RegimeSnapshot

_PERSISTED_FIELDS = (
    "growth_score",
    "growth_bucket",
    "inflation_score",
    "inflation_bucket",
    "monetary_policy_score",
    "monetary_policy_bucket",
    "financial_conditions_score",
    "financial_conditions_bucket",
    "regime_label",
    "regime_confidence",
)


@dataclass
class CategoryScore:
    category: MacroCategory
    score: float | None  # composite signed z-score; None if no indicator had enough data
    bucket: int | None  # -2..+2; None iff score is None
    momentum: float | None  # change in composite score over the configured lookback


def _indicator_specs(category: MacroCategory) -> list[dict]:
    config = load_yaml_config("macro_indicators")
    return config.get("indicators", {}).get(category.value, [])


def _bucket(score: float) -> int:
    thresholds = load_yaml_config("regime")["buckets"]
    if score < thresholds["strong_negative_max"]:
        return -2
    if score < thresholds["negative_max"]:
        return -1
    if score < thresholds["positive_min"]:
        return 0
    if score < thresholds["strong_positive_min"]:
        return 1
    return 2


def compute_category_score(
    session: Session, country: str, category: MacroCategory, *, as_of: dt.date
) -> CategoryScore:
    """Composite score for one category: the mean of its indicators' signed z-scores.

    "Signed" means flipped per config where a higher raw value means the *opposite* of
    the category's positive direction - see macro_indicators.yaml's comment on
    `invert` for the sign convention. Indicators lacking enough history yet, or not
    tracked for this country (an indicator's optional `countries` allow-list in
    config), are simply excluded from the average rather than treated as zero.
    """
    specs = _indicator_specs(category)
    signed_scores: list[float] = []
    signed_momenta: list[float] = []

    for spec in specs:
        allowed_countries = spec.get("countries")
        if allowed_countries is not None and country not in allowed_countries:
            continue

        sign = -1.0 if spec.get("invert") else 1.0

        z = rolling_zscore(session, country, spec["code"], as_of=as_of)
        if z is not None:
            signed_scores.append(sign * z)

        momentum = zscore_momentum(session, country, spec["code"], as_of=as_of)
        if momentum is not None:
            signed_momenta.append(sign * momentum)

    if not signed_scores:
        return CategoryScore(category=category, score=None, bucket=None, momentum=None)

    score = sum(signed_scores) / len(signed_scores)
    momentum_avg = sum(signed_momenta) / len(signed_momenta) if signed_momenta else None
    return CategoryScore(
        category=category, score=score, bucket=_bucket(score), momentum=momentum_avg
    )


def classify_regime(
    growth: CategoryScore,
    inflation: CategoryScore,
    monetary_policy: CategoryScore,
    financial_conditions: CategoryScore,
) -> tuple[RegimeLabel, float]:
    """Transparent decision tree over the four category buckets/momenta.

    Returns (regime_label, confidence). Confidence is a distance-from-decision-
    boundary heuristic (config/regime.yaml's confidence.saturation_distance), not a
    fitted probability - it says how solidly inside its bucket/threshold the deciding
    score sits, nothing more.
    """
    rules = load_yaml_config("regime")["regime_rules"]
    scale = load_yaml_config("regime")["confidence"]["saturation_distance"]

    g_bucket = growth.bucket if growth.bucket is not None else 0
    i_bucket = inflation.bucket if inflation.bucket is not None else 0
    mp_bucket = monetary_policy.bucket if monetary_policy.bucket is not None else 0
    fc_bucket = financial_conditions.bucket if financial_conditions.bucket is not None else 0
    g_momentum = growth.momentum if growth.momentum is not None else 0.0

    def dist_confidence(score: float | None, boundary: float) -> float:
        if score is None or scale <= 0:
            return 0.0
        return min(1.0, abs(score - boundary) / scale)

    # 1. Financial-stress overrides take precedence over the growth/inflation quadrant.
    if (
        fc_bucket <= rules["liquidity_crisis_financial_conditions_max"]
        and g_bucket <= rules["liquidity_crisis_growth_max"]
    ):
        confidence = dist_confidence(
            financial_conditions.score, rules["liquidity_crisis_financial_conditions_max"]
        )
        return RegimeLabel.LIQUIDITY_CRISIS, confidence

    if fc_bucket <= rules["risk_off_financial_conditions_max"]:
        confidence = dist_confidence(
            financial_conditions.score, rules["risk_off_financial_conditions_max"]
        )
        return RegimeLabel.RISK_OFF, confidence

    # 2. Growth turning points (momentum-based, ahead of the static quadrant below).
    if (
        g_bucket <= rules["recovery_growth_max"]
        and g_momentum > rules["recovery_momentum_min"]
        and i_bucket <= rules["recovery_inflation_max"]
    ):
        return RegimeLabel.RECOVERY, dist_confidence(g_momentum, rules["recovery_momentum_min"])

    if (
        g_bucket >= rules["late_cycle_growth_min"]
        and g_momentum < rules["late_cycle_momentum_max"]
        and mp_bucket >= rules["late_cycle_monetary_policy_min"]
    ):
        return RegimeLabel.LATE_CYCLE, dist_confidence(g_momentum, rules["late_cycle_momentum_max"])

    # 3. Growth/inflation quadrant - exhaustive over integer buckets: g_bucket
    #    partitions into {>=0, <=-1} and i_bucket into {<=0, >=1}, covering all four
    #    combinations, so the final DEFLATION case needs no extra condition.
    growth_confidence = dist_confidence(growth.score, 0.0)
    inflation_confidence = dist_confidence(inflation.score, 0.5)
    quadrant_confidence = (growth_confidence + inflation_confidence) / 2

    if g_bucket >= 0 and i_bucket <= 0:
        return RegimeLabel.GOLDILOCKS, quadrant_confidence
    if g_bucket >= 0 and i_bucket >= 1:
        return RegimeLabel.REFLATION, quadrant_confidence
    if g_bucket <= -1 and i_bucket >= 1:
        return RegimeLabel.STAGFLATION, quadrant_confidence
    return RegimeLabel.DEFLATION, quadrant_confidence


def compute_snapshot(
    session: Session, country: str, *, as_of: dt.date, model_version: str = "v1"
) -> RegimeSnapshot:
    """Compute (but do not persist) a RegimeSnapshot for one country/date."""
    growth = compute_category_score(session, country, MacroCategory.GROWTH, as_of=as_of)
    inflation = compute_category_score(session, country, MacroCategory.INFLATION, as_of=as_of)
    monetary_policy = compute_category_score(
        session, country, MacroCategory.MONETARY_POLICY, as_of=as_of
    )
    financial_conditions = compute_category_score(
        session, country, MacroCategory.FINANCIAL_CONDITIONS, as_of=as_of
    )

    regime_label, confidence = classify_regime(
        growth, inflation, monetary_policy, financial_conditions
    )

    return RegimeSnapshot(
        country=country,
        as_of=as_of,
        growth_score=growth.score,
        growth_bucket=growth.bucket,
        inflation_score=inflation.score,
        inflation_bucket=inflation.bucket,
        monetary_policy_score=monetary_policy.score,
        monetary_policy_bucket=monetary_policy.bucket,
        financial_conditions_score=financial_conditions.score,
        financial_conditions_bucket=financial_conditions.bucket,
        regime_label=regime_label,
        regime_confidence=confidence,
        model_version=model_version,
    )


def compute_and_persist_snapshot(
    session: Session, country: str, *, as_of: dt.date, model_version: str = "v1"
) -> RegimeSnapshot:
    """Compute a snapshot and upsert it - safe to re-run for the same (country, as_of,
    model_version): overwrites the existing row's computed fields rather than
    duplicating it.
    """
    existing = session.scalar(
        select(RegimeSnapshot).where(
            RegimeSnapshot.country == country,
            RegimeSnapshot.as_of == as_of,
            RegimeSnapshot.model_version == model_version,
        )
    )
    snapshot = compute_snapshot(session, country, as_of=as_of, model_version=model_version)

    if existing is not None:
        for field in _PERSISTED_FIELDS:
            setattr(existing, field, getattr(snapshot, field))
        session.flush()
        return existing

    session.add(snapshot)
    session.flush()
    return snapshot


def regime_history(
    session: Session, country: str, *, model_version: str = "v1"
) -> list[RegimeSnapshot]:
    stmt = (
        select(RegimeSnapshot)
        .where(RegimeSnapshot.country == country, RegimeSnapshot.model_version == model_version)
        .order_by(RegimeSnapshot.as_of)
    )
    return list(session.scalars(stmt))


@dataclass
class RegimeStatus:
    current: RegimeLabel
    confidence: float
    as_of: dt.date
    previous: RegimeLabel | None
    duration_periods: int
    transition_probabilities: dict[str, float]


def regime_status(
    session: Session, country: str, *, model_version: str = "v1"
) -> RegimeStatus | None:
    """Current regime plus duration/previous-regime/transition-probability context,
    derived from this country's persisted RegimeSnapshot history.
    """
    history = regime_history(session, country, model_version=model_version)
    if not history:
        return None

    latest = history[-1]
    duration = 1
    previous: RegimeLabel | None = None
    for snapshot in reversed(history[:-1]):
        if snapshot.regime_label == latest.regime_label:
            duration += 1
        else:
            previous = snapshot.regime_label
            break

    return RegimeStatus(
        current=latest.regime_label,
        confidence=latest.regime_confidence,
        as_of=latest.as_of,
        previous=previous,
        duration_periods=duration,
        transition_probabilities=next_regime_transition_probabilities(
            session, country, model_version=model_version
        ),
    )


def estimate_transition_matrix(
    session: Session, country: str, *, model_version: str = "v1"
) -> dict[str, dict[str, float]]:
    """Empirical Markov transition matrix from this country's regime history: for
    each regime, the historical frequency of moving to each other regime at the next
    snapshot. A frequency count, not a fitted model - it needs a reasonable amount of
    history to mean anything, and with little history it just reflects too few
    observations rather than anything predictive.
    """
    history = regime_history(session, country, model_version=model_version)
    counts: dict[str, dict[str, int]] = {}
    for previous, current in pairwise(history):
        from_regime = previous.regime_label.value
        to_regime = current.regime_label.value
        bucket = counts.setdefault(from_regime, {})
        bucket[to_regime] = bucket.get(to_regime, 0) + 1

    matrix: dict[str, dict[str, float]] = {}
    for from_regime, to_counts in counts.items():
        total = sum(to_counts.values())
        matrix[from_regime] = {to_regime: count / total for to_regime, count in to_counts.items()}
    return matrix


def next_regime_transition_probabilities(
    session: Session, country: str, *, model_version: str = "v1"
) -> dict[str, float]:
    """Probability of moving to each regime at the next snapshot, given the current
    regime and this country's historical transition frequencies.
    """
    history = regime_history(session, country, model_version=model_version)
    if not history:
        return {}
    matrix = estimate_transition_matrix(session, country, model_version=model_version)
    return matrix.get(history[-1].regime_label.value, {})
