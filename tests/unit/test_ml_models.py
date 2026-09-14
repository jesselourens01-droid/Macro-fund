from __future__ import annotations

import numpy as np
import pytest

from jlmacro.models.ml.models import MODEL_FACTORIES, build_model


@pytest.mark.parametrize("name", sorted(MODEL_FACTORIES))
def test_build_model_returns_a_fresh_fittable_estimator(name):
    rng = np.random.default_rng(0)
    x = rng.normal(size=(40, 5))
    y = (x[:, 0] > 0).astype(int)

    model = build_model(name)
    model.fit(x, y)
    predictions = model.predict(x)

    assert len(predictions) == 40
    assert set(predictions.tolist()) <= {0, 1}


def test_build_model_rejects_unknown_name():
    with pytest.raises(ValueError, match="unknown model"):
        build_model("not_a_real_model")


def test_build_model_returns_independent_instances():
    a = build_model("logistic")
    b = build_model("logistic")
    assert a is not b
