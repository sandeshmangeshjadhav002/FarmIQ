"""Supabase client factory.

A single privileged client is created with the **service-role key**, which
bypasses Row Level Security. Because of that, every data-access function in
``db.py`` filters by the authenticated user's id explicitly. The RLS policies
in ``supabase/migrations/0001_init.sql`` act as a defence-in-depth backstop.
"""
from __future__ import annotations

import logging
from typing import Any

from .config import get_settings
from .errors import AppError

logger = logging.getLogger("farmiq.supabase")


class SupabaseNotConfiguredError(AppError):
    """Raised when Supabase credentials are missing at request time.

    Subclasses AppError so the central error handler returns a clean 503
    instead of a generic 500.
    """

    def __init__(self, message: str):
        super().__init__(503, message)


def get_admin_client() -> Any:
    """FastAPI dependency returning the privileged Supabase client.

    Tests override this via ``app.dependency_overrides[get_admin_client] = ...``.
    """
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise SupabaseNotConfiguredError(
            "Supabase credentials not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in backend/.env"
        )
    try:
        from supabase import create_client
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError("The 'supabase' package is not installed.") from exc
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
