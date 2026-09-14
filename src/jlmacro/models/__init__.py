"""Core ORM models.

Importing this package registers every mapped class against jlmacro.database.Base's
registry, which Alembic's env.py relies on for autogenerate and which SQLAlchemy needs
to resolve string-based relationship() references between modules.

Sub-packages models/macro, models/signals, models/ml, models/regime hold *statistical*
model definitions/artifacts (regime classifiers, signal models, ML models) introduced
from Phase 3 onward - not to be confused with the ORM models here.
"""

from jlmacro.models.audit import AuditLogEntry
from jlmacro.models.enums import AssetClass, Frequency, MacroCategory, TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.portfolio import Portfolio, Position, Trade

__all__ = [
    "AssetClass",
    "AuditLogEntry",
    "Frequency",
    "Instrument",
    "MacroCategory",
    "MacroDataPoint",
    "MarketDataPoint",
    "Portfolio",
    "Position",
    "Trade",
    "TradeDirection",
    "TradeStatus",
]
