from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.config import load_yaml_config
from jlmacro.data.loader import seed_instruments, seed_macro_data, seed_market_data
from jlmacro.models.regime import compute_and_persist_snapshot

_START = dt.date(2024, 1, 1)
_END = dt.date(2026, 6, 30)


@pytest.fixture()
def seeded(db_session):
    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=_START, end=_END)
    seed_macro_data(db_session, start=_START, end=_END)
    for country in load_yaml_config("macro_indicators")["countries"]:
        compute_and_persist_snapshot(db_session, country, as_of=_END)
    db_session.flush()
    return [i.symbol for i in instruments]


def test_post_ml_evaluate_endpoint(client, seeded):
    dates = [dt.date(2025, 1, 1) + dt.timedelta(days=21 * i) for i in range(8)]
    resp = client.post(
        "/ml/evaluate",
        json={
            "symbols": seeded[:5],
            "dates": [d.isoformat() for d in dates],
            "horizon_days": 21,
            "model_names": ["logistic", "random_forest"],
            "n_splits": 3,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dataset_rows"] > 0
    names = {r["model_name"] for r in body["results"]}
    assert names == {"logistic", "random_forest"}
    for result in body["results"]:
        assert len(result["folds"]) == 3
        assert 0.0 <= result["mean_model_accuracy"] <= 1.0


def test_post_ml_evaluate_404s_when_no_rows_can_be_built(client, db_session):
    seed_instruments(db_session)
    db_session.flush()
    resp = client.post(
        "/ml/evaluate",
        json={
            "symbols": ["SPX"],
            "dates": [dt.date(2025, 1, 1).isoformat()],
        },
    )
    assert resp.status_code == 404
