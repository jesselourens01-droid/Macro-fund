"""Provider-agnostic data adapter interface.

Every external data source (FRED, RBA, ABS, ECB, a market data vendor, ...) gets its own
adapter class implementing this interface. Adapters are the only code allowed to know a
given provider's quirks (auth, pagination, field names, units); everything downstream
consumes the standardised records this interface returns.

Phase 1 ships only SyntheticMarketDataProvider and SyntheticMacroDataProvider so the
whole stack runs without any paid/free API keys. Real adapters (FredProvider, RBAProvider,
ABSProvider, ...) are added in Phase 2 behind this same interface.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from typing import Any


class BaseDataProvider(ABC):
    """Common interface for all data providers."""

    name: str

    @abstractmethod
    def fetch(
        self,
        *,
        identifiers: list[str],
        start: dt.date,
        end: dt.date,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Return a list of standardised PIT records for the requested identifiers
        and date range. Each record must be shaped so it can be loaded directly into
        the corresponding ORM model (MarketDataPoint or MacroDataPoint fields).
        """
        raise NotImplementedError


class BaseMarketDataProvider(BaseDataProvider):
    """Specialisation for providers that return price bars."""


class BaseMacroDataProvider(BaseDataProvider):
    """Specialisation for providers that return macroeconomic observations."""
