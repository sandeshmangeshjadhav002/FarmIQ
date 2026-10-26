"""ML prediction endpoints + history.

Each endpoint runs the existing preprocessing pipeline via ml.adapter and a
trained model IF one is present. When no model file exists the adapter raises
ModelNotAvailableError (-> HTTP 501), except irrigation which uses the existing
rule-based baseline. Every successful prediction is recorded to history.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app import db
from app.auth import get_current_user, get_current_user_optional
from app.schemas import (
    CropPredictionRequest,
    FertilizerPredictionRequest,
    IrrigationPredictionRequest,
    PredictionResponse,
    YieldPredictionRequest,
)
from app.supabase_client import get_admin_client
from ml.adapter import get_adapter

router = APIRouter()


def _save(client, user_id, domain, input_data, output, source):
    try:
        db.insert_prediction(client, user_id, domain, input_data, output, source)
    except Exception as exc:  # history is best-effort; never fail a prediction on it
        import logging
        logging.getLogger("farmiq.predictions").warning("insert_prediction failed: %s", exc)


@router.post("/api/predictions/crop", response_model=PredictionResponse)
def predict_crop(payload: CropPredictionRequest, user=Depends(get_current_user_optional), client=Depends(get_admin_client)):
    data = payload.model_dump()
    result = get_adapter().predict_crop(data)
    out = {"domain": "crop", "prediction": result["prediction"], "source": "model",
           "details": result.get("details")}
    if user:
        _save(client, user.id, "crop", data, {"prediction": result["prediction"]}, "model")
    return out


@router.post("/api/predictions/fertilizer", response_model=PredictionResponse)
def predict_fertilizer(payload: FertilizerPredictionRequest, user=Depends(get_current_user_optional), client=Depends(get_admin_client)):
    data = payload.model_dump()
    result = get_adapter().predict_fertilizer(data)
    out = {"domain": "fertilizer", "prediction": result["prediction"], "source": "model",
           "details": result.get("details")}
    if user:
        _save(client, user.id, "fertilizer", data, {"prediction": result["prediction"]}, "model")
    return out


@router.post("/api/predictions/yield", response_model=PredictionResponse)
def predict_yield(payload: YieldPredictionRequest, user=Depends(get_current_user_optional), client=Depends(get_admin_client)):
    data = payload.model_dump()
    result = get_adapter().predict_yield(data)
    out = {"domain": "yield", "prediction": result["prediction"], "source": "model",
           "details": result.get("details")}
    if user:
        _save(client, user.id, "yield", data, {"prediction": result["prediction"]}, "model")
    return out


@router.post("/api/predictions/irrigation", response_model=PredictionResponse)
def predict_irrigation(payload: IrrigationPredictionRequest, user=Depends(get_current_user_optional), client=Depends(get_admin_client)):
    data = payload.model_dump()
    result = get_adapter().predict_irrigation(data)
    out = {"domain": "irrigation", "prediction": result["prediction"],
           "source": result.get("source", "model"), "label": result.get("label"),
           "details": result.get("details")}
    if user:
        _save(client, user.id, "irrigation", data,
              {"prediction": result["prediction"], "label": result.get("label")}, out["source"])
    return out


@router.get("/api/predictions")
def list_predictions(
    user=Depends(get_current_user),
    client=Depends(get_admin_client),
    domain: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows, total = db.list_predictions(client, user.id, domain, limit, offset)
    return {"items": [r for r in rows], "total": total, "limit": limit, "offset": offset}
