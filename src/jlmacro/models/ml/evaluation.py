"""Walk-forward validation against a baseline - the only way a model here is
trusted with more than a look. `TimeSeriesSplit` trains on an earlier chronological
block and tests on a strictly later one for every fold (never shuffled, never
randomly split), so no fold's training features can ever include what a later
fold's forward-return labels reveal. The baseline is a majority-class predictor
fit on each fold's own training labels - "does the model beat guessing the more
common outcome," the least a model has to clear to be worth anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from jlmacro.models.ml.features import FEATURE_COLUMNS
from jlmacro.models.ml.models import build_model


@dataclass
class FoldResult:
    fold: int
    train_size: int
    test_size: int
    model_accuracy: float
    model_auc: float | None
    baseline_accuracy: float


@dataclass
class EvaluationResult:
    model_name: str
    folds: list[FoldResult] = field(default_factory=list)

    @property
    def mean_model_accuracy(self) -> float:
        return float(np.mean([f.model_accuracy for f in self.folds])) if self.folds else 0.0

    @property
    def mean_baseline_accuracy(self) -> float:
        return float(np.mean([f.baseline_accuracy for f in self.folds])) if self.folds else 0.0

    @property
    def mean_model_auc(self) -> float | None:
        aucs = [f.model_auc for f in self.folds if f.model_auc is not None]
        return float(np.mean(aucs)) if aucs else None

    @property
    def beats_baseline(self) -> bool:
        return self.mean_model_accuracy > self.mean_baseline_accuracy


def walk_forward_evaluate(
    dataset: pd.DataFrame, model_name: str, *, n_splits: int = 5
) -> EvaluationResult:
    if len(dataset) < n_splits + 1:
        raise ValueError(
            f"dataset has only {len(dataset)} rows; need at least {n_splits + 1} for "
            f"{n_splits} walk-forward splits"
        )

    ordered = dataset.sort_values("date").reset_index(drop=True)
    features = ordered[FEATURE_COLUMNS].to_numpy()
    target = ordered["target"].to_numpy()

    result = EvaluationResult(model_name=model_name)
    splitter = TimeSeriesSplit(n_splits=n_splits)

    for fold_index, (train_idx, test_idx) in enumerate(splitter.split(features)):
        x_train, x_test = features[train_idx], features[test_idx]
        y_train, y_test = target[train_idx], target[test_idx]

        model = build_model(model_name)
        model.fit(x_train, y_train)
        predictions = model.predict(x_test)
        model_accuracy = float(accuracy_score(y_test, predictions))

        model_auc: float | None = None
        if len(set(y_test)) > 1 and hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(x_test)[:, 1]
            model_auc = float(roc_auc_score(y_test, probabilities))

        majority_class = round(float(np.mean(y_train))) if len(y_train) else 0
        baseline_predictions = np.full_like(y_test, majority_class)
        baseline_accuracy = float(accuracy_score(y_test, baseline_predictions))

        result.folds.append(
            FoldResult(
                fold=fold_index,
                train_size=len(train_idx),
                test_size=len(test_idx),
                model_accuracy=model_accuracy,
                model_auc=model_auc,
                baseline_accuracy=baseline_accuracy,
            )
        )

    return result


def compare_models(
    dataset: pd.DataFrame, model_names: list[str], *, n_splits: int = 5
) -> dict[str, EvaluationResult]:
    return {name: walk_forward_evaluate(dataset, name, n_splits=n_splits) for name in model_names}
