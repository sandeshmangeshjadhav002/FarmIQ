"""Data-access layer over Supabase Postgres.

Every function takes the privileged Supabase client as its first argument and
filters by the authenticated user's id explicitly. This is the primary
authorization mechanism (the service-role key bypasses RLS); the RLS policies
in supabase/migrations/0001_init.sql are a defence-in-depth backstop.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .errors import AppError, ConflictError, NotFoundError

logger = logging.getLogger("farmiq.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exec(query: Any) -> Any:
    """Execute a Supabase query builder and return the response object."""
    return query.execute()


def _data(resp: Any) -> Any:
    return getattr(resp, "data", None) if not isinstance(resp, dict) else resp.get("data")


def _count(resp: Any) -> int | None:
    c = getattr(resp, "count", None) if not isinstance(resp, dict) else resp.get("count")
    return c


# ─────────────────────────────────────────────────────────────────────────
# Profiles
# ─────────────────────────────────────────────────────────────────────────

def get_profile(client: Any, uid: str) -> dict[str, Any]:
    resp = client.table("profiles").select("*").eq("id", uid).single().execute()
    data = _data(resp)
    if not data:
        raise NotFoundError("User profile not found.")
    return data


def get_profile_by_mobile(client: Any, mobile: str) -> dict[str, Any] | None:
    resp = client.table("profiles").select("*").eq("mobile", mobile).limit(1).execute()
    rows = _data(resp) or []
    return rows[0] if rows else None


def create_profile(
    client: Any, uid: str, full_name: str, email: str, mobile: str, role: str
) -> dict[str, Any]:
    row = {
        "id": uid,
        "full_name": full_name,
        "email": email.lower(),
        "mobile": mobile,
        "role": role,
        "created_at": _now_iso(),
    }
    try:
        resp = client.table("profiles").insert(row).execute()
    except Exception as exc:
        logger.error("create_profile failed: %s", exc)
        raise ConflictError("Profile could not be created.") from exc
    data = _data(resp)
    return data[0] if isinstance(data, list) and data else row


def update_profile(client: Any, uid: str, fields: dict[str, Any]) -> dict[str, Any]:
    resp = client.table("profiles").update(fields).eq("id", uid).execute()
    rows = _data(resp) or []
    if not rows:
        raise NotFoundError("User profile not found.")
    return rows[0]


# ─────────────────────────────────────────────────────────────────────────
# Farms
# ─────────────────────────────────────────────────────────────────────────

def list_farms(client: Any, owner_id: str, limit: int = 20, offset: int = 0) -> tuple[list, int]:
    resp = (
        client.table("farms")
        .select("*", count="exact")
        .eq("owner_id", owner_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return _data(resp) or [], _count(resp) or 0


def get_farm(client: Any, owner_id: str, farm_id: str) -> dict[str, Any]:
    resp = client.table("farms").select("*").eq("id", farm_id).eq("owner_id", owner_id).maybe_single().execute()
    data = _data(resp)
    if not data:
        raise NotFoundError("Farm not found.")
    return data


def create_farm(client: Any, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = {**payload, "id": str(uuid.uuid4()), "owner_id": owner_id, "created_at": _now_iso()}
    resp = client.table("farms").insert(row).execute()
    data = _data(resp)
    return data[0] if isinstance(data, list) and data else row


def update_farm(client: Any, owner_id: str, farm_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    resp = client.table("farms").update(fields).eq("id", farm_id).eq("owner_id", owner_id).execute()
    rows = _data(resp) or []
    if not rows:
        raise NotFoundError("Farm not found.")
    return rows[0]


def delete_farm(client: Any, owner_id: str, farm_id: str) -> None:
    resp = client.table("farms").delete().eq("id", farm_id).eq("owner_id", owner_id).execute()
    rows = _data(resp) or []
    if not rows:
        raise NotFoundError("Farm not found.")


# ─────────────────────────────────────────────────────────────────────────
# Devices
# ─────────────────────────────────────────────────────────────────────────

def list_devices(client: Any, owner_id: str, limit: int = 50, offset: int = 0) -> tuple[list, int]:
    resp = (
        client.table("devices")
        .select("*", count="exact")
        .eq("owner_id", owner_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return _data(resp) or [], _count(resp) or 0


def get_device(client: Any, owner_id: str, device_id: str) -> dict[str, Any]:
    resp = client.table("devices").select("*").eq("id", device_id).eq("owner_id", owner_id).maybe_single().execute()
    data = _data(resp)
    if not data:
        raise NotFoundError("Device not found.")
    return data


def pair_device(client: Any, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("farm_id"):
        # Ensure the farm belongs to this user before assigning.
        get_farm(client, owner_id, payload["farm_id"])
    device_id = str(uuid.uuid4())
    device_token = secrets.token_urlsafe(32)
    row = {
        "id": device_id,
        "owner_id": owner_id,
        "name": payload["name"],
        "farm_id": payload.get("farm_id"),
        "config": payload.get("config", "soil_sensor"),
        "device_token": device_token,
        "is_online": True,
        "last_seen_at": _now_iso(),
        "created_at": _now_iso(),
    }
    resp = client.table("devices").insert(row).execute()
    data = _data(resp)
    return data[0] if isinstance(data, list) and data else row


def delete_device(client: Any, owner_id: str, device_id: str) -> None:
    resp = client.table("devices").delete().eq("id", device_id).eq("owner_id", owner_id).execute()
    rows = _data(resp) or []
    if not rows:
        raise NotFoundError("Device not found.")


def get_device_by_token(client: Any, device_id: str, device_token: str) -> dict[str, Any] | None:
    resp = (
        client.table("devices")
        .select("*")
        .eq("id", device_id)
        .eq("device_token", device_token)
        .limit(1)
        .execute()
    )
    rows = _data(resp) or []
    return rows[0] if rows else None


def touch_device(client: Any, device_id: str) -> None:
    client.table("devices").update({"last_seen_at": _now_iso(), "is_online": True}).eq("id", device_id).execute()


# ─────────────────────────────────────────────────────────────────────────
# Sensor readings
# ─────────────────────────────────────────────────────────────────────────

def insert_sensor_reading(
    client: Any, owner_id: str, farm_id: str | None, payload: dict[str, Any]
) -> dict[str, Any]:
    row = {
        "id": str(uuid.uuid4()),
        "owner_id": owner_id,
        "farm_id": farm_id,
        # Hardware ingestion never sets this, so real readings are explicitly
        # marked non-demo. The simulator passes is_demo=True in ``payload``,
        # which overrides this default — demo rows can never be confused with
        # real ones.
        "is_demo": False,
        "created_at": _now_iso(),
        **{k: v for k, v in payload.items() if v is not None},
    }
    resp = client.table("sensor_readings").insert(row).execute()
    data = _data(resp)
    return data[0] if isinstance(data, list) and data else row


def list_sensor_readings(
    client: Any,
    owner_id: str,
    device_id: str | None = None,
    farm_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    is_demo: bool | None = None,
) -> tuple[list, int]:
    q = client.table("sensor_readings").select("*", count="exact").eq("owner_id", owner_id)
    if device_id:
        q = q.eq("device_id", device_id)
    if farm_id:
        q = q.eq("farm_id", farm_id)
    if is_demo is not None:
        # Lets the UI switch between real hardware readings and DEMO data.
        q = q.eq("is_demo", is_demo)
    resp = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return _data(resp) or [], _count(resp) or 0


# ─────────────────────────────────────────────────────────────────────────
# Prediction history
# ─────────────────────────────────────────────────────────────────────────

def insert_prediction(
    client: Any,
    owner_id: str,
    domain: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    row = {
        "id": str(uuid.uuid4()),
        "owner_id": owner_id,
        "domain": domain,
        "input": input_data,
        "output": output_data,
        "source": source,
        "created_at": _now_iso(),
    }
    resp = client.table("predictions").insert(row).execute()
    data = _data(resp)
    return data[0] if isinstance(data, list) and data else row


def list_predictions(
    client: Any, owner_id: str, domain: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list, int]:
    q = client.table("predictions").select("*", count="exact").eq("owner_id", owner_id)
    if domain:
        q = q.eq("domain", domain)
    resp = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return _data(resp) or [], _count(resp) or 0


# ─────────────────────────────────────────────────────────────────────────
# Farming methods advisor — saved plans
#
# The reference content (methods, alternatives) lives in dedicated tables that
# are read through ``farming_service``; only user-created plans are written here.
# ─────────────────────────────────────────────────────────────────────────

VALID_PLAN_KINDS = ("comparison", "transition_plan")


def insert_farming_plan(
    client: Any,
    owner_id: str,
    kind: str,
    input_data: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Persist a farmer's saved comparison or transition plan (owner-scoped)."""
    if kind not in VALID_PLAN_KINDS:
        raise ConflictError(f"Unknown plan kind '{kind}'.")
    row = {
        "id": str(uuid.uuid4()),
        "owner_id": owner_id,
        "kind": kind,
        "crop": input_data.get("crop"),
        "preference": input_data.get("preference"),
        "farm_id": input_data.get("farm_id"),
        "input": input_data,
        "result": result,
        "created_at": _now_iso(),
    }
    resp = client.table("farming_plans").insert(row).execute()
    data = _data(resp)
    return data[0] if isinstance(data, list) and data else row


def list_farming_plans(
    client: Any, owner_id: str, kind: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list, int]:
    q = client.table("farming_plans").select("*", count="exact").eq("owner_id", owner_id)
    if kind:
        q = q.eq("kind", kind)
    resp = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return _data(resp) or [], _count(resp) or 0


def get_farming_plan(client: Any, owner_id: str, plan_id: str) -> dict[str, Any]:
    resp = (
        client.table("farming_plans")
        .select("*")
        .eq("id", plan_id)
        .eq("owner_id", owner_id)
        .maybe_single()
        .execute()
    )
    data = _data(resp)
    if not data:
        raise NotFoundError("Farming plan not found.")
    return data


# ─────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────

def _count_rows(client: Any, table: str, owner_id: str, extra: dict[str, Any] | None = None) -> int:
    q = client.table(table).select("id", count="exact").eq("owner_id", owner_id)
    for col, val in (extra or {}).items():
        q = q.eq(col, val)
    resp = q.execute()
    return _count(resp) or 0


def dashboard_summary(client: Any, owner_id: str) -> dict[str, Any]:
    farms = _count_rows(client, "farms", owner_id)
    devices = _count_rows(client, "devices", owner_id)
    devices_online = _count_rows(client, "devices", owner_id, extra={"is_online": True})
    predictions = _count_rows(client, "predictions", owner_id)

    readings_rows, readings_total = list_sensor_readings(client, owner_id, limit=1, offset=0)
    latest = readings_rows[0] if readings_rows else None
    return {
        "farms": farms,
        "devices": devices,
        "devices_online": devices_online,
        "recent_readings": readings_total,
        "predictions": predictions,
        "latest_reading": latest,
    }
