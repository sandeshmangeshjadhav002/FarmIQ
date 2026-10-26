"""Dashboard summary endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app import db
from app.auth import get_current_user
from app.schemas import DashboardSummary
from app.supabase_client import get_admin_client

router = APIRouter()


@router.get("/api/dashboard/summary", response_model=DashboardSummary)
def summary(user=Depends(get_current_user), client=Depends(get_admin_client)):
    return db.dashboard_summary(client, user.id)
