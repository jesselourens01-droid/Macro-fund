from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.data.loader import seed_instruments, seed_market_data

_START = dt.date(2024, 1, 1)
_END = dt.date(2026, 6, 30)  # ~2.5 years, comfortably past every engine's min_observations
_AS_OF = dt.date(2026, 6, 30)
_SYMBOLS = "SPX,US10Y,XAU,EURUSD"


@pytest.fixture()
def seeded(db_session):
    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=_START, end=_END)
    db_session.flush()
    return instruments


def test_get_covariance_endpoint(client, seeded):
    resp = client.get(
        "/portfolio/covariance", params={"symbols": _SYMBOLS, "as_of": _AS_OF.isoformat()}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["symbols"]) == {"SPX", "US10Y", "XAU", "EURUSD"}
    assert body["method"] == "ledoit_wolf"
    for symbol in body["symbols"]:
        assert body["annualised_volatility"][symbol] > 0
        assert body["covariance"][symbol][symbol] > 0


def test_get_covariance_rejects_unknown_method(client, seeded):
    resp = client.get(
        "/portfolio/covariance",
        params={"symbols": _SYMBOLS, "as_of": _AS_OF.isoformat(), "method": "bogus"},
    )
    assert resp.status_code == 400


def test_get_covariance_requires_two_symbols(client, seeded):
    resp = client.get(
        "/portfolio/covariance", params={"symbols": "SPX", "as_of": _AS_OF.isoformat()}
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("weighting_method", ["inverse_volatility", "equal_risk_contribution"])
def test_get_weights_endpoint_scales_to_target_volatility(client, seeded, weighting_method):
    resp = client.get(
        "/portfolio/weights",
        params={
            "symbols": _SYMBOLS,
            "as_of": _AS_OF.isoformat(),
            "weighting_method": weighting_method,
            "target_volatility": 0.08,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_volatility"] == pytest.approx(0.08)
    assert body["portfolio_volatility"] == pytest.approx(0.08, abs=1e-6)
    assert set(body["weights"].keys()) == {"SPX", "US10Y", "XAU", "EURUSD"}
    assert sum(body["risk_contributions"].values()) == pytest.approx(1.0, abs=1e-3)


def test_get_position_size_endpoint(client, seeded):
    resp = client.get(
        "/portfolio/sizing/SPX",
        params={"nav": 10_000_000, "risk_units": 1.0, "direction": 1, "as_of": _AS_OF.isoformat()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "SPX"
    assert body["risk_budget"] == pytest.approx(10_000_000 * 0.0050)
    assert body["notional"] is not None and body["notional"] > 0


def test_post_exposures_endpoint(client, seeded):
    resp = client.post(
        "/portfolio/exposures",
        json={
            "weights": {"SPX": 0.3, "US10Y": -0.2, "XAU": 0.15, "EURUSD": 0.1},
            "as_of": _AS_OF.isoformat(),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["gross"] == pytest.approx(0.75)
    assert body["net"] == pytest.approx(0.35)
    assert body["portfolio_volatility"] > 0
    assert set(body["marginal_contribution_to_risk"].keys()) == {"SPX", "US10Y", "XAU", "EURUSD"}


def test_post_exposures_requires_two_symbols(client, seeded):
    resp = client.post(
        "/portfolio/exposures", json={"weights": {"SPX": 1.0}, "as_of": _AS_OF.isoformat()}
    )
    assert resp.status_code == 400
