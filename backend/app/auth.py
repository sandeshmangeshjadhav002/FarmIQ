"""Authentication dependencies.

Tokens are verified server-side through Supabase (``client.auth.get_user``).
The returned ``AuthUser`` carries the Supabase auth uid and the matching
``profiles`` row. Resource ownership is enforced in ``db.py`` by filtering on
``AuthUser.id``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException

from . import db
from .errors import AuthorizationError
from .supabase_client import get_admin_client

logger = logging.getLogger("farmiq.auth")


@dataclass
class AuthUser:
    id: str
    email: str
    profile: dict[str, Any]


def _extract_bearer(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise HTTPException(status_code=401, detail="Invalid Authorization header.")
    return parts[1]


def _user_attr(user: Any, name: str, default: Any = None) -> Any:
    if user is None:
        return default
    if hasattr(user, name):
        return getattr(user, name)
    if isinstance(user, dict):
        return user.get(name, default)
    return default


def get_current_user(
    authorization: Optional[str] = Header(None),
    client: Any = Depends(get_admin_client),
) -> AuthUser:
    token = _extract_bearer(authorization)
    try:
        resp = client.auth.get_user(token)
    except Exception as exc:  # supabase raises on invalid/expired tokens
        # Log only the exception *type*: some auth errors embed the submitted
        # token or URL in their message, which must never reach the logs.
        logger.warning("Token verification failed (%s).", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user = _user_attr(resp, "user")
    uid = _user_attr(user, "id")
    email = _user_attr(user, "email", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    profile = db.get_profile(client, uid)
    return AuthUser(id=uid, email=email or profile.get("email", ""), profile=profile)


def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    client: Any = Depends(get_admin_client),
) -> Optional[AuthUser]:
    """Like get_current_user but returns None when no token is present.

    Used by sensor ingestion which accepts either a user token or a device token.
    """
    if not authorization:
        return None
    try:
        return get_current_user(authorization=authorization, client=client)
    except HTTPException:
        return None


def require_owner(resource_owner_id: str, auth_user: AuthUser) -> None:
    """Defence-in-depth ownership check used alongside RLS policies."""
    if not resource_owner_id or resource_owner_id != auth_user.id:
        raise AuthorizationError("You do not have access to this resource.")
