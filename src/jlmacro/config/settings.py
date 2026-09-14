"""Environment-driven settings.

Secrets and environment-specific values (DB credentials, ports, feature flags) live here
and are sourced from environment variables / .env. Fund business rules (risk limits, asset
universe, etc.) live in the YAML files under config/ and are loaded separately via
jlmacro.config.loader.load_yaml_config so they can be edited without touching code or
restarting with new env vars.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    jlmacro_env: str = "development"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "jlmacro"
    postgres_user: str = "jlmacro"
    postgres_password: str = "change_me_dev_password"

    jlmacro_database_url: str | None = None

    jlmacro_api_host: str = "0.0.0.0"
    jlmacro_api_port: int = 8000

    jlmacro_dashboard_port: int = 8501
    jlmacro_api_base_url: str = "http://localhost:8000"

    jlmacro_config_dir: str = "config"

    jlmacro_log_level: str = "INFO"
    jlmacro_log_format: str = "json"

    # Hard safety default. This must never be True except via an explicit, reviewed
    # override alongside broker-specific safeguards (see src/jlmacro/execution).
    jlmacro_live_trading_enabled: bool = False

    # Real macro data provider credentials (Phase 2). None of these are required for
    # Phase 1's synthetic data path. RBA and ABS do not require API keys.
    fred_api_key: str | None = None

    # Shared HTTP client behaviour for outbound provider calls (src/jlmacro/data/http.py).
    jlmacro_http_timeout_seconds: float = 30.0

    @computed_field  # type: ignore[misc]
    @property
    def database_url(self) -> str:
        if self.jlmacro_database_url:
            return self.jlmacro_database_url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[misc]
    @property
    def config_dir_path(self) -> Path:
        return Path(self.jlmacro_config_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()
