"""Health & status endpoints (no auth required)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.errors import AppError
from app.supabase_client import get_admin_client
from ml.adapter import get_adapter

router = APIRouter()


@router.get("/")
def root():
    return {"message": "FarmIQ backend is running"}


@router.get("/api/health")
def health(client=Depends(get_admin_client)):
    """Lightweight DB connectivity check.

    ``get_admin_client`` raises SupabaseNotConfiguredError (-> 503) if the
    service-role credentials are missing; otherwise we ping the DB.
    """
    try:
        client.table("profiles").select("id", count="exact").limit(0).execute()
    except Exception as exc:  # noqa: BLE001
        raise AppError(503, f"Database connection failed: {exc}")
    return {"status": "healthy", "database": "connected"}


@router.get("/api/health/ml")
def health_ml():
    """Report which ML domains have preprocessing artefacts and trained models."""
    try:
        return {"models": get_adapter().status()}
    except Exception as exc:  # noqa: BLE001
        raise AppError(503, f"ML status unavailable: {exc}")
