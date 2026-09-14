"""The pre-trade gate every broker construction must pass through.

Per the platform spec, live trading must be disabled by default and requires
explicit human approval plus broker-specific safeguards before any order can be
transmitted. `assert_broker_permitted` is that gate: it is called before a broker is
even instantiated for use, not just before an order is submitted, so a live broker
can never come into existence in a session where live trading isn't enabled - there
is no path around it. As of this phase there is no live broker to construct
(`PaperBroker` is the only concrete implementation), so this only actually rejects
something once a live broker exists; it is written now so that broker is required
to go through it from day one.
"""

from __future__ import annotations

from jlmacro.config import get_settings


class LiveTradingDisabledError(RuntimeError):
    pass


def assert_broker_permitted(broker_name: str, *, actor: str | None = None) -> None:
    if broker_name == "paper":
        return

    settings = get_settings()
    if not settings.jlmacro_live_trading_enabled:
        raise LiveTradingDisabledError(
            f"live broker '{broker_name}' is disabled: "
            "JLMACRO_LIVE_TRADING_ENABLED is not set. Live trading requires an "
            "explicit, reviewed override plus broker-specific safeguards."
        )
    if not actor:
        raise LiveTradingDisabledError(
            f"live broker '{broker_name}' requires a named human actor to construct, "
            "never an automated/system caller."
        )
