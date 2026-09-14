from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.data.loader import seed_instruments, seed_macro_data, seed_market_data

_START = dt.date(2024, 1, 1)
_END = dt.date(2025, 12, 31)


@pytest.fixture()
def seeded(db_session):
    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=_START, end=_END)
    seed_macro_data(db_session, start=_START, end=_END)
    db_session.flush()
    return [i.symbol for i in instruments]


def test_post_backtest_run_endpoint(client, seeded):
    resp = client.post(
        "/backtest/run",
        json={
            "symbols": seeded,
            "start": "2025-01-01",
            "end": "2025-07-01",
            "nav0": 10_000_000,
            "rebalance_frequency_days": 63,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["periods"]) > 0
    assert body["periods"][0]["nav_start"] == pytest.approx(10_000_000)
    assert 0.0 <= body["hit_rate"] <= 1.0


def test_post_backtest_walk_forward_endpoint(client, seeded):
    resp = client.post(
        "/backtest/walk-forward",
        json={
            "symbols": seeded,
            "start": "2025-01-01",
            "end": "2025-07-01",
            "window_days": 90,
            "rebalance_frequency_days": 63,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["windows"]) == len(body["results"])
    assert len(body["windows"]) > 1


def test_post_backtest_monte_carlo_endpoint(client):
    resp = client.post(
        "/backtest/monte-carlo",
        json={
            "period_returns": [0.01, -0.02, 0.015, -0.005, 0.02],
            "nav0": 1_000_000,
            "num_simulations": 1000,
            "seed": 5,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    p = body["terminal_nav_percentiles"]
    assert p["p5"] <= p["p50"] <= p["p95"]
