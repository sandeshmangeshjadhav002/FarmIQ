"""Farm context handed to the AI assistant as *background facts*.

Both AI entry points (``POST /api/chat`` and the voice assistant's
``intent=unknown`` fallback) describe the farmer's own farm to the model so an
answer fits their land instead of being generic advice. This module is the
single definition of *which* fields may be shared, so nothing sensitive and
nothing invented can reach the model by accident.

Two rules, both enforced here:

* Only fields listed below are copied — coordinates, device tokens, owner ids
  and row ids are never included.
* A field is included only when it actually has a value in the database.
  Nothing is inferred, averaged, rounded or defaulted, so the assistant can
  never be told something about the farm that FarmIQ does not know.
"""
from __future__ import annotations

from typing import Any, Optional

# Columns of the ``farms`` table that describe the farm itself.
FARM_FIELDS = (
    "name",
    "location",
    "area_value",
    "area_unit",
    "soil_type",
    "current_crop",
    "irrigation_type",
)

# Channel list for the newest ``sensor_readings`` row.
# Channels a standard FarmIQ soil probe is expected to report. Used for
# completeness checks ("which channel is missing?"), so an optional extra such
# as air pressure is never reported as a missing reading.
REQUIRED_READING_FIELDS = (
    "soil_moisture",
    "soil_temperature",
    "temperature",
    "humidity",
    "nitrogen",
    "phosphorous",
    "potassium",
    "ph",
)

# Everything from the newest reading worth sharing as live context, including
# optional extras. Only values actually present in the row are forwarded.
READING_FIELDS = (*REQUIRED_READING_FIELDS, "pressure")


def build_farm_context(
    farm: Optional[dict],
    reading: Optional[dict] = None,
) -> Optional[dict]:
    """Build the assistant's farm-context dict from a farm and a reading row.

    Returns ``None`` when neither row contributes a value, so the caller can
    pass ``None`` straight through and leave the prompt unchanged.
    """
    context: dict = {}

    if isinstance(farm, dict):
        for key in FARM_FIELDS:
            value = farm.get(key)
            if value not in (None, ""):
                context[key] = value

    if isinstance(reading, dict):
        for key in READING_FIELDS:
            value = reading.get(key)
            if value not in (None, ""):
                context[key] = value
        if context:
            # DEMO/simulated readings must never be presented as real hardware
            # data, so the model is told which it is.
            context["latest_reading_source"] = (
                "DEMO simulated" if reading.get("is_demo") else "device"
            )
            if reading.get("created_at"):
                context["latest_reading_at"] = reading["created_at"]

    return context or None


def load_farm_context(client: Any, owner_id: str) -> Optional[dict]:
    """Fetch the newest farm + newest sensor reading and build the context.

    Best-effort by design: a database error yields whatever was collected so
    far (usually ``None``) rather than failing the request, because the
    assistant must stay usable when farm data is missing.
    """
    from app import db

    farm: Optional[dict] = None
    reading: Optional[dict] = None

    try:
        farms, _ = db.list_farms(client, owner_id, limit=1, offset=0)
        farm = farms[0] if farms else None
    except Exception:  # noqa: BLE001 - best-effort context only
        farm = None

    try:
        readings, _ = db.list_sensor_readings(client, owner_id, limit=1, offset=0)
        reading = readings[0] if readings else None
    except Exception:  # noqa: BLE001 - best-effort context only
        reading = None

    return build_farm_context(farm, reading)
