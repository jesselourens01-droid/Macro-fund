"""Macro regime endpoints.

Read-only over jlmacro.models.regime's persisted RegimeSnapshot history - this router
does not compute anything itself; snapshots are produced by
scripts/compute_regime_snapshots.py (or any caller of
jlmacro.models.regime.compute_and_persist_snapshot) and simply read back here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import RegimeSnapshotOut, RegimeStatusOut
from jlmacro.config import load_yaml_config
from jlmacro.models.regime import regime_history, regime_status
from jlmacro.models.regime_snapshot import RegimeSnapshot

router = APIRouter(prefix="/regime", tags=["regime"])


@router.get("", response_model=dict[str, RegimeSnapshotOut | None])
def regime_matrix(db: Session = Depends(get_db)) -> dict[str, RegimeSnapshot | None]:
    """Latest regime snapshot for every configured country (config/macro_indicators.yaml's
    `countries` list) - powers the dashboard's country regime matrix. A country with no
    computed snapshot yet maps to null rather than being omitted.
    """
    countries = load_yaml_config("macro_indicators").get("countries", [])
    result: dict[str, RegimeSnapshot | None] = {}
    for country in countries:
        history = regime_history(db, country)
        result[country] = history[-1] if history else None
    return result


@router.get("/{country}", response_model=RegimeStatusOut)
def get_regime_status(country: str, db: Session = Depends(get_db)) -> RegimeStatusOut:
    status = regime_status(db, country.upper())
    if status is None:
        raise HTTPException(status_code=404, detail=f"No regime snapshots for '{country}' yet")
    return RegimeStatusOut(
        country=country.upper(),
        current=status.current,
        confidence=status.confidence,
        as_of=status.as_of,
        previous=status.previous,
        duration_periods=status.duration_periods,
        transition_probabilities=status.transition_probabilities,
    )


@router.get("/{country}/history", response_model=list[RegimeSnapshotOut])
def get_regime_history(country: str, db: Session = Depends(get_db)) -> list[RegimeSnapshot]:
    return regime_history(db, country.upper())
