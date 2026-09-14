"""Candidate models for the ML research layer - logistic regression, an elastic-net-
penalised logistic regression, a random forest, and a gradient-boosted model
(LightGBM; `xgboost` is also a declared dependency and a drop-in alternative,
picked here for its lighter default footprint). Every factory returns a fresh,
unfitted estimator - callers (`jlmacro.models.ml.evaluation`) are responsible for
fitting one per walk-forward fold, never reusing a fitted instance across folds.
"""

from __future__ import annotations

from collections.abc import Callable

from lightgbm import LGBMClassifier
from sklearn.base import ClassifierMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

_RANDOM_STATE = 42

MODEL_FACTORIES: dict[str, Callable[[], ClassifierMixin]] = {
    "logistic": lambda: LogisticRegression(max_iter=1000, random_state=_RANDOM_STATE),
    # l1_ratio in (0, 1) implies elastic-net regularisation without passing the
    # now-deprecated `penalty="elasticnet"` (sklearn >= 1.8).
    "elastic_net_logistic": lambda: LogisticRegression(
        solver="saga",
        l1_ratio=0.5,
        max_iter=2000,
        random_state=_RANDOM_STATE,
    ),
    "random_forest": lambda: RandomForestClassifier(
        n_estimators=200, max_depth=5, random_state=_RANDOM_STATE
    ),
    "gradient_boosting": lambda: LGBMClassifier(
        n_estimators=200, max_depth=5, random_state=_RANDOM_STATE, verbose=-1
    ),
}


def build_model(name: str) -> ClassifierMixin:
    factory = MODEL_FACTORIES.get(name)
    if factory is None:
        raise ValueError(f"unknown model '{name}'; choose one of {sorted(MODEL_FACTORIES)}")
    return factory()
