"""Sensor ingestion + history endpoints.

Ingestion accepts EITHER:
  * a user access token (the reading's ``device_id`` must belong to that user), OR
  * a device token with the ``X-Device-Id`` header (ESP32 devices authenticate
    with the token returned at pairing time; an optional shared
    ``SENSOR_INGEST_TOKEN`` may also be used for admin/test ingestion).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query

from app import db
from app.auth import get_current_user
from app.config import get_settings
from app.errors import AppError
from app.schemas import SensorReadingIn, SensorReadingOut
from app.supabase_client import get_admin_client

logger = logging.getLogger("farmiq.sensors")
router = APIRouter()


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1]:
        return parts[1]
    return None


@router.post("/api/sensor-readings/ingest", response_model=SensorReadingOut, status_code=201)
def ingest_reading(
    payload: SensorReadingIn,
    authorization: Optional[str] = Header(None),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    client=Depends(get_admin_client),
):
    token = _bearer(authorization)
    settings = get_settings()

    if x_device_id:
        # ── Device-auth path (ESP32) ────────────────────────────────────
        if not token:
            raise AppError(401, "Device ingestion requires a bearer device token.")
        device = None
        if settings.sensor_ingest_token and token == settings.sensor_ingest_token:
            resp = client.table("devices").select("*").eq("id", x_device_id).limit(1).execute()
            rows = getattr(resp, "data", None) or []
            device = rows[0] if rows else None
        else:
            device = db.get_device_by_token(client, x_device_id, token)
        if not device:
            raise AppError(401, "Invalid device credentials.")
        if payload.device_id != device["id"]:
            raise AppError(400, "device_id does not match X-Device-Id.")
        db.touch_device(client, device["id"])
        owner_id, farm_id, device_id = device["owner_id"], device.get("farm_id"), device["id"]
        logger.info("Ingest via device %s for user %s", device_id, owner_id)
    else:
        # ── User-token path ─────────────────────────────────────────────
        if not token:
            raise AppError(401, "Provide a user access token or a device token with X-Device-Id.")
        user = get_current_user(authorization=authorization, client=client)
        try:
            device = db.get_device(client, user.id, payload.device_id)
        except Exception:
            raise AppError(403, "Device does not belong to your account.")
        owner_id, farm_id, device_id = user.id, device.get("farm_id"), device["id"]

    row = db.insert_sensor_reading(
        client,
        owner_id,
        farm_id,
        {
            "device_id": device_id,
            "soil_moisture": payload.soil_moisture,
            "soil_temperature": payload.soil_temperature,
            "temperature": payload.temperature,
            "humidity": payload.humidity,
            "soil_moisture_raw": payload.soil_moisture_raw,
            "pressure": payload.pressure,
        },
    )
    return SensorReadingOut(**row)


@router.get("/api/sensor-readings")
def list_readings(
    user=Depends(get_current_user),
    client=Depends(get_admin_client),
    device_id: Optional[str] = Query(None),
    farm_id: Optional[str] = Query(None),
    source: str = Query("all", pattern="^(all|real|demo)$",
                        description="all = both, real = hardware only, demo = simulator only"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    is_demo = {"all": None, "real": False, "demo": True}[source]
    rows, total = db.list_sensor_readings(
        client, user.id, device_id, farm_id, limit, offset, is_demo=is_demo
    )
    return {
        "items": [r for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "source": source,
    }
