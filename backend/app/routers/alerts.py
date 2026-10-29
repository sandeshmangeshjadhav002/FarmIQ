"""Alerts & Notifications endpoints.

Endpoints
---------
``POST  /api/alerts/refresh``      – re-run the alert rules over the caller's
                                     own data, persist the result, return the list.
``GET   /api/alerts``              – the caller's alerts (newest first, paginated).
``PATCH /api/alerts/{alert_id}``   – set an alert's read/unread state.
``POST  /api/alerts/read-all``     – mark every unread alert as read.

Every endpoint requires authentication and is scoped to the caller's own rows.

Alerts are *derived*, never invented: the rules run over data the account
already owns (device contact times, recent readings, saved drought assessments,
stored predictions). An account with none of that data gets an empty list, not
placeholder content. Re-running ``refresh`` updates existing alerts in place
via their dedup key, so the list never accumulates duplicates.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from app import alerts_service, db
from app.auth import AuthUser, get_current_user
from app.schemas import (
    AlertBulkReadResponse,
    AlertListResponse,
    AlertReadRequest,
)
from app.supabase_client import get_admin_client

logger = logging.getLogger("farmiq.alerts")

router = APIRouter()

# Safety cap so one refresh cannot fan out into an unbounded number of reads.
_MAX_DEVICES = 100


def _build_context(client: Any, owner_id: str) -> dict[str, Any]:
    """Assemble the rule-engine input from the caller's stored data.

    Only owner-scoped reads. Missing pieces stay absent (``None`` / empty) so
    the corresponding rules simply do not fire.
    """
    devices, _ = db.list_devices(client, owner_id, limit=_MAX_DEVICES, offset=0)

    latest_reading_by_device: dict[str, dict[str, Any]] = {}
    for device in devices:
        device_id = device.get("id")
        if not device_id:
            continue
        rows, _ = db.list_sensor_readings(
            client, owner_id, device_id=device_id, limit=1, offset=0
        )
        if rows:
            latest_reading_by_device[device_id] = rows[0]

    latest_assessment = None
    assessment_row = db.get_latest_drought_assessment(client, owner_id)
    if assessment_row:
        result = assessment_row.get("result") or {}
        latest_assessment = {
            "id": assessment_row.get("id"),
            "crop": assessment_row.get("crop"),
            "location": assessment_row.get("location"),
            "drought_severity": result.get("drought_severity"),
            "drought_severity_reason": result.get("drought_severity_reason"),
            "weather": result.get("weather") or assessment_row.get("weather_snapshot") or {},
        }

    predictions, _ = db.list_predictions(client, owner_id, limit=20, offset=0)

    return {
        "devices": devices,
        "latest_reading_by_device": latest_reading_by_device,
        "latest_assessment": latest_assessment,
        "latest_predictions": predictions,
    }


def _respond(client: Any, owner_id: str, limit: int, offset: int) -> dict[str, Any]:
    items, total = db.list_alerts(client, owner_id, limit=limit, offset=offset)
    return {"total": total, "unread": db.count_unread_alerts(client, owner_id), "items": items}


@router.post("/api/alerts/refresh", response_model=AlertListResponse)
def refresh_alerts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthUser = Depends(get_current_user),
    client: Any = Depends(get_admin_client),
):
    """Re-evaluate the alert rules and persist any changes.

    Failures while persisting a single alert are logged and skipped rather
    than failing the whole refresh, so one bad rule cannot blank the screen.
    """
    context = _build_context(client, user.id)
    drafts = alerts_service.derive_alerts(context)

    for draft in drafts:
        try:
            db.upsert_alert(client, user.id, draft)
        except Exception as exc:  # noqa: BLE001 — one alert must not break the refresh
            logger.warning("Failed to persist alert %s: %s", draft.get("dedup_key"), exc)

    logger.info("Alert refresh for user %s produced %d draft(s)", user.id, len(drafts))
    return _respond(client, user.id, limit, offset)


@router.get("/api/alerts", response_model=AlertListResponse)
def list_alerts(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthUser = Depends(get_current_user),
    client: Any = Depends(get_admin_client),
):
    """The caller's alerts, newest first."""
    items, total = db.list_alerts(
        client, user.id, unread_only=unread_only, limit=limit, offset=offset
    )
    return {"total": total, "unread": db.count_unread_alerts(client, user.id), "items": items}


@router.patch("/api/alerts/{alert_id}", response_model=AlertListResponse)
def update_alert(
    alert_id: str,
    payload: AlertReadRequest,
    user: AuthUser = Depends(get_current_user),
    client: Any = Depends(get_admin_client),
):
    """Mark a single alert read or unread (owner-scoped)."""
    db.set_alert_read(client, user.id, alert_id, payload.is_read)
    return _respond(client, user.id, limit=50, offset=0)


@router.post("/api/alerts/read-all", response_model=AlertBulkReadResponse)
def read_all_alerts(
    user: AuthUser = Depends(get_current_user),
    client: Any = Depends(get_admin_client),
):
    """Mark every unread alert as read."""
    return {"updated": db.mark_all_alerts_read(client, user.id)}
