"""Drought Management & Water Conservation endpoints.

Endpoints
---------
``POST /api/drought/assess``    – run the full drought assessment.
``GET  /api/drought/history``   – the caller's saved assessments (summary list).
``GET  /api/drought/history/{id}`` – full detail of a saved assessment.

All POST endpoints require authentication. The GET history endpoints are also
authenticated and filter strictly by the authenticated user's id.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from app import db, drought_service
from app.auth import AuthUser, get_current_user
from app.errors import NotFoundError
from app.schemas import (
    DroughtAssessmentRequest,
    DroughtAssessmentResponse,
    DroughtHistoryResponse,
)
from app.supabase_client import get_admin_client

logger = logging.getLogger("farmiq.drought")

router = APIRouter()


@router.post("/api/drought/assess", response_model=DroughtAssessmentResponse)
def assess_drought(
    payload: DroughtAssessmentRequest,
    user: AuthUser = Depends(get_current_user),
    client: Any = Depends(get_admin_client),
):
    """Run a full drought management assessment for the farmer's conditions.

    Weather is fetched live from Open-Meteo (key-less) when ``fetch_weather``
    is true. RAG context is retrieved when the knowledge base is available.
    Neither failure blocks the assessment — data gaps are reported in the
    response instead of raising an error.
    """
    # Verify farm ownership if farm_id supplied
    if payload.farm_id:
        try:
            db.get_farm(client, user.id, payload.farm_id)
        except NotFoundError:
            pass  # farm not found for this user — ignore farm_id

    input_data = payload.model_dump()
    result = drought_service.assess_drought(input_data)

    # Persist if requested
    saved_id = None
    if payload.save:
        try:
            weather_snapshot = result.get("weather") or {}
            row = db.insert_drought_assessment(
                client,
                user.id,
                input_data,
                result,
                weather_snapshot=weather_snapshot if weather_snapshot.get("fetched") else None,
            )
            saved_id = row.get("id")
            result = {**result, "saved_assessment_id": saved_id}
        except Exception as exc:  # history is best-effort
            logger.warning("Failed to persist drought assessment: %s", exc)

    return result


@router.get("/api/drought/history", response_model=DroughtHistoryResponse)
def drought_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthUser = Depends(get_current_user),
    client: Any = Depends(get_admin_client),
):
    """Paginated list of the caller's saved drought assessments (summary only)."""
    rows, total = db.list_drought_assessments(client, user.id, limit=limit, offset=offset)
    return {"total": total, "items": rows}


@router.get("/api/drought/history/{assessment_id}")
def drought_assessment_detail(
    assessment_id: str,
    user: AuthUser = Depends(get_current_user),
    client: Any = Depends(get_admin_client),
):
    """Full detail of a single saved drought assessment (owner-scoped)."""
    row = db.get_drought_assessment(client, user.id, assessment_id)
    return row
