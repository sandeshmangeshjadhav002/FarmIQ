"""Health & status endpoints (no auth required).

Three distinct probes, because they answer different questions and a deployment
platform acts on them differently:

* ``GET /api/health/live``  — *liveness*: "is this process up?" No dependencies
  are touched, so a dead database can never make the container look dead and
  trigger a restart loop.
* ``GET /api/health/ready`` — *readiness*: "can this instance serve traffic?"
  Pings the database and reports ML/RAG availability. Returns 503 only when the
  database is unreachable.
* ``GET /api/health``       — backwards-compatible aggregate kept because
  ``render.yaml`` points its health check here and the frontend may poll it.

Nothing here reveals secrets: only booleans, counts, versions and directory
*names* (never their contents or environment values).
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends

from app.config import API_VERSION
from app.errors import AppError
from app.supabase_client import get_admin_client
from ml.adapter import get_adapter

logger = logging.getLogger("farmiq.health")

router = APIRouter()

_STARTED_AT = time.monotonic()


def _uptime_seconds() -> float:
    return round(time.monotonic() - _STARTED_AT, 3)


def _database_ok(client) -> tuple[bool, str]:
    """Cheap connectivity probe. Never raises; returns (ok, message)."""
    try:
        client.table("profiles").select("id", count="exact").limit(0).execute()
        return True, "connected"
    except Exception as exc:  # noqa: BLE001 - probe must never propagate
        logger.warning("Database probe failed: %s", type(exc).__name__)
        return False, f"unreachable ({type(exc).__name__})"


@router.get("/")
def root():
    return {"message": "FarmIQ backend is running", "version": API_VERSION}


@router.get("/health")
def health_simple():
    """Dependency-free reachability probe for phone/emulator connectivity tests."""
    return {"status": "ok", "version": API_VERSION}


@router.get("/api/health/live")
def liveness():
    """Liveness probe — process only, no external dependencies."""
    return {"status": "alive", "version": API_VERSION, "uptime_seconds": _uptime_seconds()}


@router.get("/api/health/ready")
def readiness(client=Depends(get_admin_client)):
    """Readiness probe — 503 unless the database answers.

    ML/RAG availability is reported but deliberately **not** fatal: predictions
    degrade to a clear 501 and the assistant to a 503 per-request, so an
    instance with no trained models can still serve the rest of the API.
    """
    ok, message = _database_ok(client)
    if not ok:
        raise AppError(503, f"Database connection failed: {message}")

    try:
        models = get_adapter().status()
    except Exception as exc:  # noqa: BLE001 - report, never fail readiness
        logger.warning("ML status unavailable during readiness probe: %s", type(exc).__name__)
        models = {"available": False, "reason": type(exc).__name__}

    return {
        "status": "ready",
        "version": API_VERSION,
        "uptime_seconds": _uptime_seconds(),
        "database": "connected",
        "models": models,
    }


@router.get("/api/health")
def health(client=Depends(get_admin_client)):
    """Aggregate health check (kept for the Render health check and the UI)."""
    ok, message = _database_ok(client)
    if not ok:
        raise AppError(503, f"Database connection failed: {message}")
    return {
        "status": "healthy",
        "version": API_VERSION,
        "uptime_seconds": _uptime_seconds(),
        "database": "connected",
    }


@router.get("/api/health/ml")
def health_ml():
    """Report which ML domains have preprocessing artefacts and trained models."""
    try:
        return {"models": get_adapter().status(), "version": API_VERSION}
    except Exception as exc:  # noqa: BLE001
        raise AppError(503, f"ML status unavailable: {exc}")
