from __future__ import annotations

import pytest

from jlmacro.config.settings import get_settings


@pytest.fixture()
def api_key_enabled(monkeypatch):
    monkeypatch.setenv("JLMACRO_API_KEY", "test-secret-key")
    get_settings.cache_clear()
    yield "test-secret-key"
    get_settings.cache_clear()


def test_api_is_open_by_default(client):
    resp = client.get("/instruments")
    assert resp.status_code == 200


def test_health_never_requires_a_key(client, api_key_enabled):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_request_without_key_is_rejected_once_a_key_is_configured(client, api_key_enabled):
    resp = client.get("/instruments")
    assert resp.status_code == 401


def test_request_with_wrong_key_is_rejected(client, api_key_enabled):
    resp = client.get("/instruments", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


def test_request_with_correct_key_is_accepted(client, api_key_enabled):
    resp = client.get("/instruments", headers={"X-API-Key": api_key_enabled})
    assert resp.status_code == 200


def test_root_endpoint_never_requires_a_key(client, api_key_enabled):
    resp = client.get("/")
    assert resp.status_code == 200
