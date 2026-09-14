"""Loader for the fund's YAML configuration files (config/*.yaml).

Business rules such as risk limits and the asset universe must never be hard-coded in
application logic. Modules that need them call load_yaml_config("risk_limits") and read
plain dicts, so a PM/risk manager can change fund parameters by editing a file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from jlmacro.config.settings import get_settings


@lru_cache
def load_yaml_config(name: str) -> dict[str, Any]:
    """Load a YAML config file by name (without extension) from the config directory.

    Example: load_yaml_config("risk_limits") -> dict from config/risk_limits.yaml
    """
    settings = get_settings()
    path = settings.config_dir_path / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def config_file_path(name: str) -> Path:
    return get_settings().config_dir_path / f"{name}.yaml"
