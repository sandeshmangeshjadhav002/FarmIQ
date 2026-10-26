"""Test fixtures.

A lightweight fake Supabase client lets the whole API be tested without any
real Supabase credentials or network. It implements the subset of the
supabase-py query-builder + auth APIs that ``app/db.py`` and ``app/auth.py``
use.
"""
from __future__ import annotations

import os
import secrets
import uuid
from pathlib import Path
from typing import Any, Optional

# Provide dummy Supabase credentials BEFORE any settings are read so the
# /api/health endpoint (which checks creds are present) works under test.
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "fake-anon-key")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import get_current_user  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.supabase_client import get_admin_client  # noqa: E402


class R:
    """Fake Supabase response object (mirrors .data/.count/.user/.session)."""

    def __init__(self, data=None, count=None, user=None, session=None):
        self.data = data
        self.count = count
        self.user = user
        self.session = session


class FakeAuth:
    def __init__(self):
        self.users: list[dict] = []          # {id, email, password, user_metadata}
        self.tokens: dict[str, dict] = {}    # access_token -> user dict
        self.admin = self                    # supabase-py exposes auth.admin.create_user

    def create_user(self, attrs: dict) -> R:
        uid = str(uuid.uuid4())
        user = {
            "id": uid,
            "email": attrs.get("email"),
            "user_metadata": attrs.get("user_metadata", {}),
        }
        self.users.append({**user, "password": attrs.get("password")})
        return R(user=user)

    def sign_in_with_password(self, creds: dict) -> R:
        for u in self.users:
            if u["email"] == creds.get("email") and u["password"] == creds.get("password"):
                token = f"tok-{u['id']}"
                self.tokens[token] = {"id": u["id"], "email": u["email"]}
                return R(user={"id": u["id"], "email": u["email"]},
                         session={"access_token": token, "refresh_token": "refresh"})
        raise Exception("Invalid credentials")

    def get_user(self, token: str) -> R:
        user = self.tokens.get(token)
        if not user:
            raise Exception("invalid token")
        return R(user=user)


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str):
        self.client = client
        self.table = table
        self._filters: list[tuple[str, Any]] = []
        self._count: Optional[str] = None
        self._order: Optional[tuple[str, bool]] = None
        self._range: Optional[tuple[int, int]] = None
        self._limit: Optional[int] = None
        self._single = False
        self._maybe_single = False
        self._op = "select"
        self._payload: Any = None

    def select(self, cols="*", count=None):
        self._count = count
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def insert(self, row):
        self._op = "insert"
        self._payload = row
        return self

    def update(self, fields):
        self._op = "update"
        self._payload = fields
        return self

    def delete(self):
        self._op = "delete"
        return self

    def _matches(self) -> list[dict]:
        rows = self.client.tables.get(self.table, [])
        return [r for r in rows if all(r.get(c) == v for c, v in self._filters)]

    def execute(self) -> R:
        if self._op == "insert":
            self.client.tables.setdefault(self.table, []).append(self._payload)
            return R(data=[self._payload])
        if self._op == "delete":
            rows = self.client.tables.get(self.table, [])
            kept = [r for r in rows if not all(r.get(c) == v for c, v in self._filters)]
            removed = [r for r in rows if all(r.get(c) == v for c, v in self._filters)]
            self.client.tables[self.table] = kept
            return R(data=removed)
        if self._op == "update":
            rows = self.client.tables.get(self.table, [])
            changed = []
            for r in rows:
                if all(r.get(c) == v for c, v in self._filters):
                    r.update(self._payload)
                    changed.append(r)
            return R(data=changed)

        # select
        matched = self._matches()
        if self._single:
            if not matched:
                raise Exception("No rows found")
            return R(data=matched[0])
        if self._maybe_single:
            return R(data=matched[0] if matched else None)
        if self._order:
            col, desc = self._order
            matched = sorted(matched, key=lambda r: r.get(col) or "", reverse=desc)
        total = len(matched)
        if self._range:
            a, b = self._range
            matched = matched[a:b + 1]
        elif self._limit:
            matched = matched[: self._limit]
        count = total if self._count == "exact" else None
        return R(data=matched, count=count)


class FakeClient:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.auth = FakeAuth()

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    # ── helpers for tests ─────────────────────────────────────────────
    def seed_profile(self, uid="u1", full_name="Ravi Kumar", email="ravi@example.com",
                     mobile="+919876543210", role="farmer"):
        profile = {"id": uid, "full_name": full_name, "email": email, "mobile": mobile,
                   "role": role, "created_at": "2025-01-01T00:00:00+00:00"}
        self.tables.setdefault("profiles", []).append(profile)
        self.auth.tokens[f"tok-{uid}"] = {"id": uid, "email": email}
        return profile

    def auth_header(self, uid="u1") -> dict:
        return {"Authorization": f"Bearer tok-{uid}"}


@pytest.fixture
def fake_client():
    return FakeClient()


@pytest.fixture(autouse=True)
def _reset_ml_adapter():
    """Ensure each test gets a fresh ML adapter (no cross-test model caching)."""
    from ml import adapter as ml_adapter
    ml_adapter._adapter = None
    yield
    ml_adapter._adapter = None


@pytest.fixture
def app_client(fake_client):
    from app.main import app

    app.dependency_overrides[get_admin_client] = lambda: fake_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def ml_tmp_models(tmp_path, monkeypatch):
    """Point the ML adapter at the real preprocessed dir but a temp models dir
    so tests don't require trained model files."""
    from app.config import get_settings
    from ml import adapter as ml_adapter

    get_settings.cache_clear()
    monkeypatch.setenv("FARMIQ_ML_PROCESSED_PATH", str(
        (get_settings().ml_processed_dir).resolve()))
    monkeypatch.setenv("FARMIQ_ML_MODELS_PATH", str(tmp_path))
    get_settings.cache_clear()
    ml_adapter._adapter = None  # reset singleton
    yield tmp_path
    ml_adapter._adapter = None
    get_settings.cache_clear()
