from __future__ import annotations

import datetime as dt

from jlmacro.data.loader import seed_instruments, seed_macro_data, seed_market_data
from jlmacro.models.regime import compute_and_persist_snapshot


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["live_trading_enabled"] is False


def test_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "docs" in resp.json()


def test_list_instruments_empty_before_seed(client):
    resp = client.get("/instruments")
    assert resp.status_code == 200
    assert resp.json() == []


def test_instrument_endpoints_after_seed(db_session, client):
    seed_instruments(db_session)

    resp = client.get("/instruments")
    assert resp.status_code == 200
    assert len(resp.json()) > 20

    resp = client.get("/instruments?asset_class=fx")
    assert resp.status_code == 200
    assert all(item["asset_class"] == "fx" for item in resp.json())

    resp = client.get("/instruments/SPX")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "SPX"

    resp = client.get("/instruments/DOES_NOT_EXIST")
    assert resp.status_code == 404


def test_market_data_endpoint(db_session, client):
    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=dt.date(2026, 1, 1), end=dt.date(2026, 2, 1))

    resp = client.get("/market-data/SPX", params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) <= 10
    assert body[0]["close"] > 0


def test_macro_data_endpoint_point_in_time(db_session, client):
    seed_instruments(db_session)
    seed_macro_data(db_session, start=dt.date(2026, 1, 1), end=dt.date(2026, 6, 1))

    resp = client.get("/macro-data/US/CPI_HEADLINE")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) > 0

    # as_of far in the past should filter out everything.
    resp = client.get("/macro-data/US/CPI_HEADLINE", params={"as_of": "2000-01-01"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_regime_endpoints(db_session, client):
    resp = client.get("/regime/US")
    assert resp.status_code == 404

    seed_instruments(db_session)
    seed_macro_data(db_session, start=dt.date(2020, 1, 1), end=dt.date(2026, 6, 1))
    compute_and_persist_snapshot(db_session, "US", as_of=dt.date(2026, 6, 30))

    resp = client.get("/regime/US")
    assert resp.status_code == 200
    body = resp.json()
    assert body["country"] == "US"
    assert body["current"] in {
        "goldilocks",
        "reflation",
        "stagflation",
        "deflation",
        "recovery",
        "late_cycle",
        "risk_off",
        "liquidity_crisis",
    }
    assert 0.0 <= body["confidence"] <= 1.0

    resp = client.get("/regime/US/history")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.get("/regime")
    assert resp.status_code == 200
    matrix = resp.json()
    assert matrix["US"] is not None
    assert matrix["AU"] is None


def test_signals_endpoints(db_session, client):
    resp = client.get("/signals/SPX")
    assert resp.status_code == 404

    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=dt.date(2023, 1, 1), end=dt.date(2026, 6, 1))
    seed_macro_data(db_session, start=dt.date(2023, 1, 1), end=dt.date(2026, 6, 1))
    compute_and_persist_snapshot(db_session, "US", as_of=dt.date(2026, 6, 30))

    resp = client.get("/signals/SPX", params={"as_of": "2026-06-30"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_symbol"] == "SPX"
    assert body["action"] in {"no_position", "watchlist", "half_unit", "full_unit", "max_unit"}
    assert body["suggested_risk_units"] in {0.0, 0.5, 1.0, 1.5}

    resp = client.get("/signals", params={"asset_class": "equity_index", "as_of": "2026-06-30"})
    assert resp.status_code == 200
    ranked = resp.json()
    assert len(ranked) > 0
    composites = [row["composite_score"] for row in ranked if row["composite_score"] is not None]
    assert composites == sorted(composites, reverse=True)
