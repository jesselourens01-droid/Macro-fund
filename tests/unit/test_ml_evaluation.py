from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from jlmacro.models.ml.evaluation import compare_models, walk_forward_evaluate
from jlmacro.models.ml.features import FEATURE_COLUMNS


def _make_informative_dataset(n_rows: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(n_rows)]
    macro = rng.uniform(0, 100, n_rows)
    # target strongly (not perfectly) driven by macro_score, so a model can learn
    # something real but walk-forward validation still has something to measure.
    noise = rng.normal(0, 15, n_rows)
    target = ((macro + noise) > 50).astype(int)

    return pd.DataFrame(
        {
            "symbol": "TEST",
            "date": dates,
            "macro_score": macro,
            "valuation_score": rng.uniform(0, 100, n_rows),
            "trend_score": rng.uniform(0, 100, n_rows),
            "positioning_score": rng.uniform(0, 100, n_rows),
            "catalyst_score": rng.uniform(0, 100, n_rows),
            "forward_return": (target - 0.5) / 10,
            "target": target,
        }
    )


def test_walk_forward_evaluate_returns_one_fold_result_per_split():
    dataset = _make_informative_dataset()
    result = walk_forward_evaluate(dataset, "logistic", n_splits=5)

    assert len(result.folds) == 5
    for fold in result.folds:
        assert 0.0 <= fold.model_accuracy <= 1.0
        assert 0.0 <= fold.baseline_accuracy <= 1.0


def test_walk_forward_evaluate_respects_chronological_split():
    dataset = _make_informative_dataset()
    ordered = dataset.sort_values("date").reset_index(drop=True)
    result = walk_forward_evaluate(dataset, "logistic", n_splits=3)

    # Reconstruct what TimeSeriesSplit should have done: train sizes strictly grow.
    train_sizes = [f.train_size for f in result.folds]
    assert train_sizes == sorted(train_sizes)
    assert sum(f.train_size + f.test_size for f in result.folds[:1]) <= len(ordered)


def test_a_strong_signal_beats_the_majority_baseline():
    dataset = _make_informative_dataset(n_rows=300, seed=3)
    result = walk_forward_evaluate(dataset, "gradient_boosting", n_splits=5)

    assert result.mean_model_accuracy > result.mean_baseline_accuracy
    assert result.beats_baseline is True


def test_walk_forward_evaluate_rejects_too_small_dataset():
    dataset = _make_informative_dataset(n_rows=3)
    with pytest.raises(ValueError, match="at least"):
        walk_forward_evaluate(dataset, "logistic", n_splits=5)


def test_compare_models_returns_one_result_per_model_name():
    dataset = _make_informative_dataset()
    results = compare_models(dataset, ["logistic", "random_forest"], n_splits=3)

    assert set(results.keys()) == {"logistic", "random_forest"}
    for result in results.values():
        assert result.model_name in {"logistic", "random_forest"}
        assert len(result.folds) == 3


def test_feature_columns_match_dataset_expectations():
    dataset = _make_informative_dataset()
    assert set(FEATURE_COLUMNS) <= set(dataset.columns)
