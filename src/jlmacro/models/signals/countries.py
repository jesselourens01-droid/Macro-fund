"""Shared currency <-> macro-country mapping for the signal engines.

Only currencies with macro data actually tracked (config/macro_indicators.yaml's
`countries` list: US, EA, GB, JP, AU, CN) can be resolved. NZD/CAD/CHF are in the FX
universe (config/assets.yaml) but not in that country list, so they intentionally
return None rather than a wrong guess - callers must handle missing coverage
gracefully (e.g. jlmacro.models.signals.valuation returns score=None for such pairs).
"""

from __future__ import annotations

_CURRENCY_TO_COUNTRY: dict[str, str] = {
    "USD": "US",
    "EUR": "EA",
    "GBP": "GB",
    "JPY": "JP",
    "AUD": "AU",
    "CNY": "CN",
}


def country_for_currency(currency: str) -> str | None:
    return _CURRENCY_TO_COUNTRY.get(currency)
