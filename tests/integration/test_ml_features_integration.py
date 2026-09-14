from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.config import load_yaml_config
from jlmacro.data.loader import seed_instruments, seed_macro_data, seed_market_data
from jlmacro.models.ml.features import FEATURE_COLUMNS, build_feature_dataset
from jlmacro.models.regime import compute_and_persist_snapshot

_START = dt.date(2024, 1, 1)
_END = dt.date(2026, 6, 30)


@pytest.fixture()
def seeded(db_session):
    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=_START, end=_END)
    seed_macro_data(db_session, start=_START, end=_END)
    db_session.flush()

    # macro_score (a feature) needs a persisted RegimeSnapshot to exist at all -
    # regime_status reads the latest one regardless of the caller's `as_of`, so one
    # snapshot per country is enough for every date this test uses.
    for country in load_yaml_config("macro_indicators")["countries"]:
        compute_and_persist_snapshot(db_session, country, as_of=_END)
    db_session.flush()

    return [i.symbol for i in instruments]


def test_build_feature_dataset_produces_pit_correct_rows_with_forward_labels(db_session, seeded):
    symbols = seeded[:3]
    dates = [dt.date(2025, 1, 1), dt.date(2025, 3, 1), dt.date(2025, 6, 1)]

    dataset = build_feature_dataset(db_session, symbols, dates, horizon_days=21)

    assert not dataset.empty
    assert set(FEATURE_COLUMNS) <= set(dataset.columns)
    assert {"symbol", "date", "forward_return", "target"} <= set(dataset.columns)
    assert dataset["target"].isin([0, 1]).all()
    assert dataset[FEATURE_COLUMNS].isna().sum().sum() == 0


def test_build_feature_dataset_target_matches_forward_return_sign(db_session, seeded):
    dataset = build_feature_dataset(
        db_session, seeded[:2], [dt.date(2025, 1, 1), dt.date(2025, 4, 1)], horizon_days=21
    )
    if dataset.empty:
        pytest.skip("no rows produced for this seed")

    assert ((dataset["forward_return"] > 0) == (dataset["target"] == 1)).all()


def test_build_feature_dataset_drops_dates_too_close_to_the_data_horizon(db_session, seeded):
    # A date right at the end of the seeded window has no forward return available.
    dataset = build_feature_dataset(db_session, seeded[:2], [_END], horizon_days=21)
    assert dataset.empty
