"""Authentication endpoints.

These broker Supabase Auth while preserving the existing frontend contract:
``/api/auth/register`` and ``/api/auth/login`` return the user profile object
plus ``access_token``/``refresh_token``. The frontend stores the whole body as
the user object and (via the new API client) captures the tokens for
protected requests.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app import db
from app.config import VALID_ROLES
from app.errors import AppError, ConflictError
from app.schemas import DEFAULT_LANGUAGE, AuthResponse, UserLogin, UserRegister
from app.supabase_client import get_admin_client, get_login_client

logger = logging.getLogger("farmiq.auth.router")
router = APIRouter()


def _attr(obj, name, default=None):
    if obj is None:
        return default
    if hasattr(obj, name):
        return getattr(obj, name)
    return obj.get(name, default) if isinstance(obj, dict) else default


def _profile_to_auth(profile: dict, access_token: str, refresh_token: str) -> AuthResponse:
    return AuthResponse(
        id=profile.get("id"),
        full_name=profile.get("full_name"),
        email=profile.get("email"),
        mobile=profile.get("mobile"),
        role=profile.get("role"),
        language=profile.get("language") or DEFAULT_LANGUAGE,
        created_at=profile.get("created_at"),
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/api/auth/register", response_model=AuthResponse, status_code=201)
def register(
    payload: UserRegister,
    client=Depends(get_admin_client),
    login_client=Depends(get_login_client),
):
    if payload.role not in VALID_ROLES:
        raise AppError(400, f"role must be one of: {', '.join(sorted(VALID_ROLES))}.")

    # Uniqueness pre-check (friendlier error than the Supabase 422).
    if db.get_profile_by_mobile(client, payload.mobile):
        raise ConflictError("Mobile number is already registered.")
    if _find_profile_by_email(client, payload.email):
        raise ConflictError("Email is already registered.")

    # Create the Supabase Auth user with email + password.
    try:
        resp = client.auth.admin.create_user(
            {
                "email": payload.email.lower(),
                "password": payload.password,
                "email_confirm": True,
                "user_metadata": {
                    "full_name": payload.full_name,
                    "mobile": payload.mobile,
                    "role": payload.role,
                },
            }
        )
    except Exception as exc:  # gotrue raises on duplicate email
        msg = str(exc).lower()
        if "already" in msg or "exists" in msg or "registered" in msg:
            raise ConflictError("Email is already registered.") from exc
        logger.error("create_user failed: %s", exc)
        raise AppError(502, f"Could not create auth user: {exc}") from exc

    auth_user = _attr(resp, "user")
    uid = _attr(auth_user, "id")
    if not uid:
        raise AppError(502, "Supabase did not return a user id.")
    try:
        db.create_profile(
            client,
            uid,
            payload.full_name,
            payload.email,
            payload.mobile,
            payload.role,
            language=payload.language,
        )
    except ConflictError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("create_profile failed: %s", exc)
        raise AppError(500, "Profile creation failed.") from exc

    access_token, refresh_token = _sign_in(login_client, payload.email, payload.password)
    profile = db.get_profile(client, uid)
    return _profile_to_auth(profile, access_token, refresh_token)


@router.post("/api/auth/login", response_model=AuthResponse)
def login(
    payload: UserLogin,
    client=Depends(get_admin_client),
    login_client=Depends(get_login_client),
):
    profile = db.get_profile_by_mobile(client, payload.mobile)
    if not profile:
        raise AppError(401, "Incorrect mobile number or password.")
    access_token, refresh_token = _sign_in(login_client, profile["email"], payload.password)
    return _profile_to_auth(profile, access_token, refresh_token)


def _find_profile_by_email(client, email: str):
    try:
        resp = client.table("profiles").select("id").eq("email", email.lower()).limit(1).execute()
        rows = getattr(resp, "data", None) or []
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("email lookup failed: %s", type(exc).__name__)
        return None


def _sign_in(login_client, email: str, password: str) -> tuple[str, str]:
    """Exchange credentials for a session on a throwaway client.

    ``sign_in_with_password`` rewrites the client's ``Authorization`` header to
    the user's token, so this must never run on the shared service-role client
    (see ``app/supabase_client.py``).
    """
    try:
        resp = login_client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:  # noqa: BLE001
        # Log the failure without the credential material.
        logger.info("sign_in failed (%s).", type(exc).__name__)
        raise AppError(401, "Incorrect mobile number or password.") from exc
    session = _attr(resp, "session")
    access_token = _attr(session, "access_token", "")
    refresh_token = _attr(session, "refresh_token", "")
    if not access_token:
        raise AppError(401, "Incorrect mobile number or password.")
    return access_token, refresh_token
