from __future__ import annotations

from jlmacro.config import get_settings, load_yaml_config


def test_settings_load_and_database_url():
    settings = get_settings()
    assert settings.postgres_db == "jlmacro_test"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "jlmacro_test" in settings.database_url


def test_settings_live_trading_disabled_by_default():
    settings = get_settings()
    assert settings.jlmacro_live_trading_enabled is False


def test_load_risk_limits_config():
    config = load_yaml_config("risk_limits")
    assert config["target_volatility"] == 0.09
    assert config["hard_volatility_limit"] > config["soft_volatility_limit"]
    assert config["position_risk"]["normal_max"] == 0.005


def test_load_assets_config_has_expected_sections():
    config = load_yaml_config("assets")
    assert "equity_indices" in config
    assert "fx" in config
    assert "rates" in config
    assert "commodities" in config
    symbols = {entry["symbol"] for entry in config["equity_indices"]}
    assert "SPX" in symbols
    assert "AS51" in symbols


def test_load_macro_indicators_config():
    config = load_yaml_config("macro_indicators")
    assert "US" in config["countries"]
    codes = {item["code"] for cat in config["indicators"].values() for item in cat}
    assert "CPI_HEADLINE" in codes


def test_load_scenarios_config():
    config = load_yaml_config("scenarios")
    ids = {s["id"] for s in config["historical_scenarios"]}
    assert "GFC_2008" in ids
    assert "COVID_2020" in ids
