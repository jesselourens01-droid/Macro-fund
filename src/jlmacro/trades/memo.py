"""Investment memo generation: a structured, human-readable snapshot of why a trade
exists, assembled entirely from what was already recorded on the `Trade` row at idea
time (`jlmacro.trades.lifecycle.create_trade_idea` populates it from the Phase 4
signal engine and Phase 5 sizing/construction output) - a memo is a *rendering* of
that record, never a second copy of it, so it can't drift from the trade it
describes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from jlmacro.models.instrument import Instrument
from jlmacro.models.portfolio import Trade


@dataclass
class InvestmentMemo:
    trade_id: str
    symbol: str
    instrument_name: str
    direction: str
    status: str
    thesis: str | None
    scores: dict[str, float | None] = field(default_factory=dict)
    regime_at_entry: str | None = None
    entry_price: float | None = None
    target_price: float | None = None
    stop_price: float | None = None
    portfolio_risk_pct: float | None = None
    position_size: float | None = None
    pm_approved_by: str | None = None
    pm_approved_at: dt.datetime | None = None
    generated_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def to_markdown(self) -> str:
        lines = [
            f"# Investment Memo: {self.symbol} ({self.direction.upper()})",
            (
                f"*Trade ID: {self.trade_id} - Status: {self.status.upper()} - "
                f"Generated: {self.generated_at.isoformat()}*"
            ),
            "",
            "## Thesis",
            self.thesis or "_No thesis recorded._",
            "",
            "## Signal breakdown (Phase 4 composite score, at idea time)",
        ]
        for label, key in [
            ("Macro", "macro_score"),
            ("Valuation", "valuation_score"),
            ("Trend", "trend_score"),
            ("Positioning", "positioning_score"),
            ("Catalyst", "catalyst_score"),
            ("Composite", "composite_score"),
        ]:
            value = self.scores.get(key)
            lines.append(
                f"- **{label}**: {value:.1f}" if value is not None else f"- **{label}**: n/a"
            )

        lines += [
            "",
            "## Regime context",
            f"Regime at entry: {self.regime_at_entry or 'n/a'}",
            "",
            "## Sizing (Phase 5)",
            f"- Entry price: {self.entry_price if self.entry_price is not None else 'n/a'}",
            f"- Target price: {self.target_price if self.target_price is not None else 'n/a'}",
            f"- Stop price: {self.stop_price if self.stop_price is not None else 'n/a'}",
            (
                f"- Portfolio risk %: "
                f"{f'{self.portfolio_risk_pct:.2%}' if self.portfolio_risk_pct is not None else 'n/a'}"
            ),
            (
                f"- Position size (notional): "
                f"{f'{self.position_size:,.0f}' if self.position_size is not None else 'n/a'}"
            ),
            "",
            "## Approval",
            f"Approved by: {self.pm_approved_by or 'not yet approved'}"
            + (f" at {self.pm_approved_at.isoformat()}" if self.pm_approved_at else ""),
        ]
        return "\n".join(lines)


def generate_investment_memo(session: Session, trade: Trade) -> InvestmentMemo:
    instrument = session.get(Instrument, trade.instrument_id)
    if instrument is None:
        raise ValueError(f"instrument {trade.instrument_id} for trade {trade.trade_id} not found")

    return InvestmentMemo(
        trade_id=trade.trade_id,
        symbol=instrument.symbol,
        instrument_name=instrument.name,
        direction=trade.direction.value,
        status=trade.status.value,
        thesis=trade.thesis,
        scores={
            "macro_score": trade.macro_score,
            "valuation_score": trade.valuation_score,
            "trend_score": trade.trend_score,
            "positioning_score": trade.positioning_score,
            "catalyst_score": trade.catalyst_score,
            "composite_score": trade.composite_score,
        },
        regime_at_entry=trade.regime_at_entry,
        entry_price=trade.entry_price,
        target_price=trade.target_price,
        stop_price=trade.stop_price,
        portfolio_risk_pct=trade.portfolio_risk_pct,
        position_size=trade.position_size,
        pm_approved_by=trade.pm_approved_by,
        pm_approved_at=trade.pm_approved_at,
    )
