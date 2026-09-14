from __future__ import annotations

from jlmacro.data.loader import seed_instruments


def test_full_trade_lifecycle_via_api(db_session, client):
    seed_instruments(db_session)
    db_session.flush()

    resp = client.post("/portfolios", json={"name": "API Test Fund", "base_currency": "AUD"})
    assert resp.status_code == 200
    portfolio_id = resp.json()["id"]

    resp = client.post(
        "/trades",
        json={
            "portfolio_id": portfolio_id,
            "symbol": "SPX",
            "direction": "long",
            "thesis": "API test thesis",
            "composite_score": 70.0,
            "entry_price": 4300.0,
            "actor": "system",
        },
    )
    assert resp.status_code == 200
    trade = resp.json()
    assert trade["status"] == "idea"
    trade_id = trade["trade_id"]

    resp = client.post(
        f"/trades/{trade_id}/transition",
        json={"new_status": "open", "actor": "jesse"},
    )
    assert resp.status_code == 400  # idea -> open is illegal, must go via approved

    resp = client.post(
        f"/trades/{trade_id}/transition",
        json={"new_status": "approved", "actor": "jesse.lourens"},
    )
    assert resp.status_code == 200
    assert resp.json()["pm_approved_by"] == "jesse.lourens"

    resp = client.post(
        f"/trades/{trade_id}/transition",
        json={"new_status": "open", "actor": "jesse.lourens"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"

    resp = client.get(f"/trades/{trade_id}/memo")
    assert resp.status_code == 200
    memo = resp.json()
    assert memo["symbol"] == "SPX"
    assert "API test thesis" in memo["markdown"]

    resp = client.get(f"/trades/{trade_id}/review")
    assert resp.status_code == 400  # not closed yet

    resp = client.post(
        f"/trades/{trade_id}/close",
        json={"exit_price": 4400.0, "actor": "jesse.lourens", "reason": "target hit"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"

    resp = client.get(f"/trades/{trade_id}/review")
    assert resp.status_code == 200
    review = resp.json()
    assert review["thesis_direction_correct"] is True

    resp = client.get("/trades", params={"portfolio_id": portfolio_id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_create_trade_idea_for_unknown_portfolio_404s(db_session, client):
    seed_instruments(db_session)
    db_session.flush()

    resp = client.post(
        "/trades",
        json={
            "portfolio_id": 999_999,
            "symbol": "SPX",
            "direction": "long",
            "thesis": "x",
        },
    )
    assert resp.status_code == 404


def test_create_trade_idea_for_unknown_symbol_404s(db_session, client):
    resp = client.post("/portfolios", json={"name": "API Test Fund 2"})
    portfolio_id = resp.json()["id"]

    resp = client.post(
        "/trades",
        json={
            "portfolio_id": portfolio_id,
            "symbol": "DOES_NOT_EXIST",
            "direction": "long",
            "thesis": "x",
        },
    )
    assert resp.status_code == 404


def test_create_duplicate_portfolio_name_conflicts(db_session, client):
    resp = client.post("/portfolios", json={"name": "Duplicate Fund"})
    assert resp.status_code == 200

    resp = client.post("/portfolios", json={"name": "Duplicate Fund"})
    assert resp.status_code == 409
