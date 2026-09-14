"""Macro regime engine.

Transparent, rule-based v1 (jlmacro.models.regime.engine) over point-in-time indicator
scoring (jlmacro.models.regime.scoring). HMM/logistic/gradient-boosted classifiers are
explicitly future work per the platform spec's Phase 3 notes; when added, they replace
engine.classify_regime but must still consume scoring's causally-computed features.
"""

from jlmacro.models.regime.engine import (
    CategoryScore,
    RegimeStatus,
    classify_regime,
    compute_and_persist_snapshot,
    compute_category_score,
    compute_snapshot,
    estimate_transition_matrix,
    next_regime_transition_probabilities,
    regime_history,
    regime_status,
)
from jlmacro.models.regime.scoring import point_in_time_history, rolling_zscore, zscore_momentum

__all__ = [
    "CategoryScore",
    "RegimeStatus",
    "classify_regime",
    "compute_and_persist_snapshot",
    "compute_category_score",
    "compute_snapshot",
    "estimate_transition_matrix",
    "next_regime_transition_probabilities",
    "point_in_time_history",
    "regime_history",
    "regime_status",
    "rolling_zscore",
    "zscore_momentum",
]
