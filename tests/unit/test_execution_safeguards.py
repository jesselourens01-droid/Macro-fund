from __future__ import annotations

import pytest

from jlmacro.execution.safeguards import LiveTradingDisabledError, assert_broker_permitted


def test_paper_broker_is_always_permitted():
    assert_broker_permitted("paper")  # must not raise


def test_live_broker_is_rejected_when_live_trading_disabled():
    with pytest.raises(LiveTradingDisabledError, match="disabled"):
        assert_broker_permitted("interactive_brokers")


def test_live_broker_rejected_even_with_actor_when_setting_disabled():
    with pytest.raises(LiveTradingDisabledError):
        assert_broker_permitted("interactive_brokers", actor="jesse.lourens")


def test_live_broker_requires_a_named_actor_even_when_enabled(monkeypatch):
    from jlmacro.config.settings import get_settings

    monkeypatch.setenv("JLMACRO_LIVE_TRADING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        with pytest.raises(LiveTradingDisabledError, match="human actor"):
            assert_broker_permitted("interactive_brokers", actor=None)

        assert_broker_permitted("interactive_brokers", actor="jesse.lourens")  # must not raise
    finally:
        get_settings.cache_clear()
