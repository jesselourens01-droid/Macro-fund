from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import InstrumentOut
from jlmacro.models.enums import AssetClass
from jlmacro.models.instrument import Instrument

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut])
def list_instruments(
    asset_class: AssetClass | None = None,
    db: Session = Depends(get_db),
) -> list[Instrument]:
    stmt = select(Instrument).where(Instrument.is_active.is_(True))
    if asset_class is not None:
        stmt = stmt.where(Instrument.asset_class == asset_class)
    return list(db.scalars(stmt.order_by(Instrument.symbol)))


@router.get("/{symbol}", response_model=InstrumentOut)
def get_instrument(symbol: str, db: Session = Depends(get_db)) -> Instrument:
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol}' not found")
    return instrument
