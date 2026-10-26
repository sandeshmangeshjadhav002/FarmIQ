"""ML prediction endpoints + history + input-validation schema.

Each endpoint:
  1. Validates the payload against the *real* supported ranges and the training
     datasets (``ml.validation``). Invalid payloads are rejected with HTTP 422
     and structured ``errors`` — values are never silently clamped or changed.
     Valid-but-outside-training-range values pass through with warnings.
  2. Runs the existing preprocessing pipeline via ``ml.adapter`` and a trained
     model IF one is present. When no model file exists the adapter raises
     ModelNotAvailableError (-> HTTP 501), except irrigation which uses the
     existing rule-based baseline.
  3. Records the prediction to history (best effort).

``GET /api/predictions/schema/{domain}`` exposes the ranges the frontend uses
to warn the user *before* submitting.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app import db
from app.auth import get_current_user, get_current_user_optional
from app.errors import InputValidationError, NotFoundError
from app.schemas import (
    CropPredictionRequest,
    FertilizerPredictionRequest,
    IrrigationPredictionRequest,
    PredictionResponse,
    ValidationSchemaResponse,
    YieldPredictionRequest,
)
from app.supabase_client import get_admin_client
from ml import validation
from ml.adapter import get_adapter

router = APIRouter()

_DOMAINS = {"crop", "fertilizer", "yield", "irrigation"}


def _validate(domain: str, data: dict) -> dict:
    """Run semantic validation; raise HTTP 422 when the input is unusable."""
    outcome = validation.validate(domain, data)
    if not outcome["ok"]:
        raise InputValidationError(
            "Input validation failed. Correct the highlighted values and try again.",
            errors=outcome["invalid"],
            warnings=[u["message"] for u in outcome["unusual"]],
            advisory=outcome["advisory"],
        )
    return outcome


def _envelope(domain: str, result: dict, outcome: dict, *, label: str | None = None) -> dict:
    """Build the consistent PredictionResponse payload with warnings/advisory."""
    return {
        "domain": domain,
        "prediction": result["prediction"],
        "source": result.get("source", "model"),
        "label": result.get("label", label),
        "details": result.get("details"),
        "recommendations": result.get("recommendations"),
        "score_type": result.get("score_type"),
        "warnings": [u["message"] for u in outcome["unusual"]],
        "unusual": outcome["unusual"],
        "advisory": validation.ACCURACY_DISCLAIMER,
    }


def _save(client, user_id, domain, input_data, output, source):
    try:
        db.insert_prediction(client, user_id, domain, input_data, output, source)
    except Exception as exc:  # history is best-effort; never fail a prediction on it
        import logging
        logging.getLogger("farmiq.predictions").warning("insert_prediction failed: %s", exc)


@router.get("/api/predictions/schema/{domain}", response_model=ValidationSchemaResponse)
def prediction_schema(domain: str):
    """Supported + training ranges for a domain (used for pre-submit warnings)."""
    if domain not in _DOMAINS:
        raise NotFoundError(f"Unknown ML domain '{domain}'. Valid: {sorted(_DOMAINS)}.")
    return validation.schema(domain)


@router.post("/api/predictions/crop", response_model=PredictionResponse)
def predict_crop(payload: CropPredictionRequest, user=Depends(get_current_user_optional), client=Depends(get_admin_client)):
    data = payload.model_dump()
    outcome = _validate("crop", data)
    result = get_adapter().predict_crop(data)
    out = _envelope("crop", result, outcome)
    if user:
        _save(client, user.id, "crop", data, {"prediction": result["prediction"]}, "model")
    return out


@router.post("/api/predictions/fertilizer", response_model=PredictionResponse)
def predict_fertilizer(payload: FertilizerPredictionRequest, user=Depends(get_current_user_optional), client=Depends(get_admin_client)):
    data = payload.model_dump()
    outcome = _validate("fertilizer", data)
    result = get_adapter().predict_fertilizer(data)
    out = _envelope("fertilizer", result, outcome)
    if user:
        _save(client, user.id, "fertilizer", data, {"prediction": result["prediction"]}, "model")
    return out


@router.post("/api/predictions/yield", response_model=PredictionResponse)
def predict_yield(payload: YieldPredictionRequest, user=Depends(get_current_user_optional), client=Depends(get_admin_client)):
    data = payload.model_dump()
    outcome = _validate("yield", data)
    result = get_adapter().predict_yield(data)
    out = _envelope("yield", result, outcome)
    if user:
        _save(client, user.id, "yield", data, {"prediction": result["prediction"]}, "model")
    return out


@router.post("/api/predictions/irrigation", response_model=PredictionResponse)
def predict_irrigation(payload: IrrigationPredictionRequest, user=Depends(get_current_user_optional), client=Depends(get_admin_client)):
    data = payload.model_dump()
    outcome = _validate("irrigation", data)
    result = get_adapter().predict_irrigation(data)
    out = _envelope("irrigation", result, outcome)
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
