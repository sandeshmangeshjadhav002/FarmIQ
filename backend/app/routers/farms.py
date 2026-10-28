"""Farm CRUD endpoints (owner-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app import db
from app.auth import get_current_user
from app.schemas import FarmCreate, FarmOut, FarmUpdate
from app.supabase_client import get_admin_client

router = APIRouter()


def _out(row: dict) -> FarmOut:
    return FarmOut(**row)


def _coord_fields(payload: FarmCreate) -> dict:
    """Payload for insert, with unknown coordinates omitted rather than sent as NULL.

    Migration 0004 adds the latitude/longitude columns. Until it is applied, an
    insert carrying those keys would be rejected ("column not found"), so an
    unknown point is left out entirely — it then defaults to NULL either way.
    """
    data = payload.model_dump()
    for key in ("latitude", "longitude"):
        if data.get(key) is None:
            data.pop(key, None)
    return data


@router.get("/api/farms")
def list_farms(
    user=Depends(get_current_user),
    client=Depends(get_admin_client),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    rows, total = db.list_farms(client, user.id, limit, offset)
    return {"items": [r for r in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/api/farms", response_model=FarmOut, status_code=201)
def create_farm(payload: FarmCreate, user=Depends(get_current_user), client=Depends(get_admin_client)):
    row = db.create_farm(client, user.id, _coord_fields(payload))
    return _out(row)


@router.get("/api/farms/{farm_id}", response_model=FarmOut)
def get_farm(farm_id: str, user=Depends(get_current_user), client=Depends(get_admin_client)):
    return _out(db.get_farm(client, user.id, farm_id))


@router.patch("/api/farms/{farm_id}", response_model=FarmOut)
def update_farm(
    farm_id: str,
    payload: FarmUpdate,
    user=Depends(get_current_user),
    client=Depends(get_admin_client),
):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    return _out(db.update_farm(client, user.id, farm_id, fields))


@router.delete("/api/farms/{farm_id}", status_code=204)
def delete_farm(farm_id: str, user=Depends(get_current_user), client=Depends(get_admin_client)):
    db.delete_farm(client, user.id, farm_id)
    return None
