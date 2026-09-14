"""Shared lookups derived from config/macro_indicators.yaml.

Keeps category/frequency/provider-series-id knowledge in one place so every real
adapter (Fred/RBA/ABS) resolves it the same way, from config, rather than each
hard-coding its own copy.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from jlmacro.config import load_yaml_config


@lru_cache
def _indicator_metadata() -> dict[str, dict[str, str]]:
    config = load_yaml_config("macro_indicators")
    result: dict[str, dict[str, str]] = {}
    for category, items in config.get("indicators", {}).items():
        for item in items:
            result[item["code"]] = {
                "category": category,
                "frequency": item.get("frequency", "monthly"),
            }
    return result


def category_for(indicator_code: str) -> str:
    return _indicator_metadata().get(indicator_code, {}).get("category", "growth")


def frequency_for(indicator_code: str) -> str:
    return _indicator_metadata().get(indicator_code, {}).get("frequency", "monthly")


def provider_series_map(provider: str) -> dict[str, dict[str, Any]]:
    """Returns {country: {indicator_code: <provider-specific identifier>}} for the
    given provider name (e.g. "FRED", "RBA", "ABS"), as configured in
    config/macro_indicators.yaml's provider_series_ids section. The per-indicator value
    is provider-specific: a bare series ID string for FRED, or a small dict (e.g.
    {"csv_url": ..., "series_id": ...} for RBA, {"dataflow": ..., "key": ...} for ABS).
    """
    config = load_yaml_config("macro_indicators")
    return config.get("provider_series_ids", {}).get(provider, {})
