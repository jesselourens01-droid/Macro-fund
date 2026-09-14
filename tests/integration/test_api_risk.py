from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.data.loader import seed_instruments, seed_market_data

_START = dt.date(2024, 1, 1)
_END = dt.date(2026, 6, 30)
_AS_OF = dt.date(2026, 6, 30)


@pytest.fixture()
def seeded(db_session):
    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=_START, end=_END)
    db_session.flush()
    return instruments


def test_post_var_endpoint_returns_all_three_methods(client, seeded):
    resp = client.post(
        "/risk/var",
        json={
            "weights": {"SPX": 0.3, "US10Y": -0.2, "XAU": 0.15, "EURUSD": 0.1},
            "as_of": _AS_OF.isoformat(),
            "nav": 10_000_000,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["methods"].keys()) == {"historical", "parametric", "monte_carlo"}
    for method_result in body["methods"].values():
        assert method_result["var_pct"] > 0
        assert method_result["es_pct"] >= method_result["var_pct"]


def test_post_var_requires_two_symbols(client, seeded):
    resp = client.post(
        "/risk/var", json={"weights": {"SPX": 1.0}, "as_of": _AS_OF.isoformat(), "nav": 1_000_000}
    )
    assert resp.status_code == 400


def test_post_hypothetical_stress_endpoint(client, seeded):
    resp = client.post(
        "/risk/stress/hypothetical",
        json={
            "weights": {"SPX": 0.3, "US10Y": -0.2, "XAU": 0.15},
            "scenario_id": "EQUITIES_DOWN_20",
            "nav": 10_000_000,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_shocks"] == {"SPX": -0.20}
    assert body["pnl_pct"] == pytest.approx(0.3 * -0.20)
    assert body["unmapped_shock_keys"] == []


def test_post_hypothetical_stress_unknown_scenario_404(client, seeded):
    resp = client.post(
        "/risk/stress/hypothetical",
        json={"weights": {"SPX": 1.0}, "scenario_id": "NOT_REAL", "nav": 1_000_000},
    )
    assert resp.status_code == 404


def test_post_historical_stress_endpoint(client, seeded):
    resp = client.post(
        "/risk/stress/historical",
        json={
            "weights": {"SPX": 0.3, "US10Y": -0.2},
            "scenario_id": "GFC_2008",
            "nav": 10_000_000,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # Synthetic seeded history doesn't cover 2008 - honestly reported as missing.
    assert set(body["missing_symbols"]) == {"SPX", "US10Y"}
    assert body["pnl_pct"] == 0.0


def test_get_drawdown_governor_endpoint(client):
    resp = client.get("/risk/drawdown", params={"current_drawdown": -0.06, "risk_budget": 50000})
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_budget_fraction"] < 1.0
    assert body["defensive_mode"] is False
    assert body["governed_risk_budget"] == pytest.approx(50000 * body["risk_budget_fraction"])


def test_get_drawdown_governor_defensive_mode(client):
    resp = client.get("/risk/drawdown", params={"current_drawdown": -0.12})
    assert resp.status_code == 200
    body = resp.json()
    assert body["defensive_mode"] is True
    assert body["governed_risk_budget"] is None
