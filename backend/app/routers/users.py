"""User profile endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app import db
from app.auth import get_current_user
from app.schemas import UserProfile, UserUpdate
from app.supabase_client import get_admin_client

router = APIRouter()


def _to_profile(p: dict) -> UserProfile:
    return UserProfile(
        id=p.get("id"),
        full_name=p.get("full_name"),
        email=p.get("email"),
        mobile=p.get("mobile"),
        role=p.get("role"),
        created_at=p.get("created_at"),
    )


@router.get("/api/users/me", response_model=UserProfile)
def me(user=Depends(get_current_user)):
    return _to_profile(user.profile)


@router.patch("/api/users/me", response_model=UserProfile)
def update_me(payload: UserUpdate, user=Depends(get_current_user), client=Depends(get_admin_client)):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        return _to_profile(user.profile)
    return _to_profile(db.update_profile(client, user.id, fields))
