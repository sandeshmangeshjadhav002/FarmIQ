"""Sensor simulator (DEMO mode) endpoints.

Lets the ML pipeline be driven end-to-end without physical hardware. Readings
are always labelled DEMO DATA and stored, when the caller opts in, with
``is_demo = true`` so they are distinguishable from real sensor rows.

Endpoints
---------
``GET  /api/simulator/config``   – channels, ranges and failure modes (public).
``POST /api/simulator/readings`` – generate one demo reading (auth required);
                                   ``persist: true`` also records it as demo.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app import db, simulator
from app.auth import get_current_user
from app.errors import AppError
from app.schemas import SimulatedReadingOut, SimulatorConfigOut, SimulatorRequest
from app.supabase_client import get_admin_client

logger = logging.getLogger("farmiq.simulator")
router = APIRouter()


@router.get("/api/simulator/config", response_model=SimulatorConfigOut)
def simulator_config():
    """Channel definitions so the frontend can build the demo controls."""
    return {
        "label": simulator.DEMO_LABEL,
        "channels": simulator.channel_specs(),
        "failure_modes": ["fail: all sensors", "fail: one or more channels"],
        "note": (
            "Readings produced here are simulated DEMO DATA, not measurements "
            "from physical hardware. Ranges follow the model training datasets."
        ),
    }


@router.post("/api/simulator/readings", response_model=SimulatedReadingOut)
def generate_reading(
    payload: SimulatorRequest,
    user=Depends(get_current_user),
    client=Depends(get_admin_client),
):
    """Generate (and optionally record) one DEMO reading."""
    unknown = [c for c in payload.overrides if c not in simulator.available_channels()]
    if unknown:
        raise AppError(
            422,
            f"Unknown channel(s): {', '.join(sorted(unknown))}. "
            f"Valid channels: {', '.join(simulator.available_channels())}.",
        )

    simulated = simulator.generate(
        seed=payload.seed,
        overrides=payload.overrides,
        fail=payload.fail,
        noise=payload.noise,
    )

    device_id = None
    record_id = None
    if payload.persist:
        if not payload.device_id:
            raise AppError(400, "device_id is required when persist is true.")
        # Ownership check: only the user's own device may hold the demo row.
        device = db.get_device(client, user.id, payload.device_id)
        device_id = device["id"]
        row = db.insert_sensor_reading(
            client, user.id, device.get("farm_id"),
            {"device_id": device_id, **simulator.to_reading_row(simulated)},
        )
        record_id = row.get("id")
        logger.info("Recorded DEMO reading %s for user %s", record_id, user.id)

    return {
        **simulated,
        "persisted": payload.persist,
        "record_id": record_id,
        "device_id": device_id,
    }
