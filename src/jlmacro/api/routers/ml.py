"""ML research layer endpoints (jlmacro.models.ml, Phase 11): builds a feature/label
dataset from the Phase 4 signal engine's own components and walk-forward-validates
candidate models against a majority-class baseline. Expensive - one
`compute_investment_score` call per symbol per date - keep symbol/date counts modest
for interactive use, same caveat as the Phase 7 backtest endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from jlmacro.api.deps import get_db
from jlmacro.api.schemas import MLEvaluateOut, MLEvaluateRequest, MLFoldOut, MLModelResultOut
from jlmacro.models.ml.evaluation import compare_models
from jlmacro.models.ml.features import build_feature_dataset

router = APIRouter(prefix="/ml", tags=["ml"])


@router.post("/evaluate", response_model=MLEvaluateOut)
def post_ml_evaluate(request: MLEvaluateRequest, db: Session = Depends(get_db)) -> MLEvaluateOut:
    dataset = build_feature_dataset(
        db, request.symbols, request.dates, horizon_days=request.horizon_days
    )
    if dataset.empty:
        raise HTTPException(
            status_code=404,
            detail=(
                "no feature/label rows could be built for these symbols/dates - check "
                "that a RegimeSnapshot exists for the relevant countries and that "
                "price history extends past the forward-return horizon"
            ),
        )

    try:
        results = compare_models(dataset, request.model_names, n_splits=request.n_splits)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return MLEvaluateOut(
        dataset_rows=len(dataset),
        results=[
            MLModelResultOut(
                model_name=result.model_name,
                folds=[
                    MLFoldOut(
                        fold=f.fold,
                        train_size=f.train_size,
                        test_size=f.test_size,
                        model_accuracy=f.model_accuracy,
                        model_auc=f.model_auc,
                        baseline_accuracy=f.baseline_accuracy,
                    )
                    for f in result.folds
                ],
                mean_model_accuracy=result.mean_model_accuracy,
                mean_baseline_accuracy=result.mean_baseline_accuracy,
                mean_model_auc=result.mean_model_auc,
                beats_baseline=result.beats_baseline,
            )
            for result in results.values()
        ],
    )
