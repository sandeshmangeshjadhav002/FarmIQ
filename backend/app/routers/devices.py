"""Device management endpoints (owner-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app import db
from app.auth import get_current_user
from app.schemas import DeviceOut, DevicePair
from app.supabase_client import get_admin_client

router = APIRouter()


@router.get("/api/devices")
def list_devices(
    user=Depends(get_current_user),
    client=Depends(get_admin_client),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows, total = db.list_devices(client, user.id, limit, offset)
    return {"items": [r for r in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/api/devices/pair", response_model=DeviceOut, status_code=201)
def pair_device(payload: DevicePair, user=Depends(get_current_user), client=Depends(get_admin_client)):
    row = db.pair_device(client, user.id, payload.model_dump())
    return DeviceOut(**row)


@router.get("/api/devices/{device_id}", response_model=DeviceOut)
def get_device(device_id: str, user=Depends(get_current_user), client=Depends(get_admin_client)):
    return DeviceOut(**db.get_device(client, user.id, device_id))


@router.delete("/api/devices/{device_id}", status_code=204)
def delete_device(device_id: str, user=Depends(get_current_user), client=Depends(get_admin_client)):
    db.delete_device(client, user.id, device_id)
    return None
