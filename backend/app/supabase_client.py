"""Supabase client factories.

A privileged client is created with the **service-role key**, which bypasses
Row Level Security. Because of that, every data-access function in ``db.py``
filters by the authenticated user's id explicitly. The RLS policies in
``supabase/migrations/0001_init.sql`` act as a defence-in-depth backstop.

Two clients, deliberately separated
-----------------------------------
``supabase-py`` keeps the *current session* on the client instance:
``auth.sign_in_with_password(...)`` fires a ``SIGNED_IN`` event which rewrites
``options.headers["Authorization"]`` to the **user's** access token and drops
the cached PostgREST client (see ``supabase/_sync/client.py::_listen_to_auth_events``).
Sharing one instance between login and data access would therefore make later
queries on that instance run as whichever user logged in last — a cross-user
data leak.

So:

* ``get_admin_client()`` — cached, service-role, **never** signs a user in.
  Used for every PostgREST query and for token verification.
* ``get_login_client()`` — a throwaway client used **only** to exchange
  credentials for a session. It is discarded immediately, so the token it
  picks up can never be observed by another request.

Both clients disable session persistence and background token refresh: the
backend is a stateless broker, so it must not open storage sessions or leak a
refresh timer thread per login.
"""
from __future__ import annotations

import logging
import threading
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


def _require_credentials() -> tuple[str, str]:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise SupabaseNotConfiguredError(
            "Supabase credentials not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in backend/.env"
        )
    return settings.supabase_url, settings.supabase_service_role_key


def _client_options() -> Any:
    """Client options for a stateless server-side client."""
    from supabase.lib.client_options import SyncClientOptions

    return SyncClientOptions(auto_refresh_token=False, persist_session=False)


def _build_client(url: str, key: str) -> Any:
    try:
        from supabase import create_client
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError("The 'supabase' package is not installed.") from exc
    return create_client(url, key, _client_options())


# One privileged client per (url, key) pair. Keyed on the credentials so a
# settings change (or a test that clears the settings cache) cannot hand back a
# stale client.
_admin_clients: dict[tuple[str, str], Any] = {}
_admin_lock = threading.Lock()


def get_admin_client() -> Any:
    """FastAPI dependency returning the privileged Supabase client.

    Cached process-wide so every request reuses the same connection pool
    instead of paying a fresh TLS handshake to Supabase per query. This
    instance must never be used for ``sign_in_with_password`` — see the module
    docstring.

    Tests override this via ``app.dependency_overrides[get_admin_client] = ...``.
    """
    url, key = _require_credentials()
    cache_key = (url, key)
    cached = _admin_clients.get(cache_key)
    if cached is not None:
        return cached
    with _admin_lock:
        cached = _admin_clients.get(cache_key)
        if cached is None:
            cached = _build_client(url, key)
            _admin_clients[cache_key] = cached
    return cached


def get_login_client() -> Any:
    """FastAPI dependency returning a throwaway client for password sign-in.

    Never cached: picking up a user session mutates the client's auth headers,
    so the instance must not outlive the single login request that created it.
    """
    url, key = _require_credentials()
    return _build_client(url, key)


def get_optional_admin_client() -> Any:
    """Like ``get_admin_client`` but returns ``None`` when Supabase is not configured.

    Used by read-only reference endpoints (e.g. the farming advisor) that can
    fall back to bundled curated content before the database is set up.
    """
    try:
        return get_admin_client()
    except SupabaseNotConfiguredError:
        logger.warning("Supabase not configured — serving curated reference content.")
        return None
