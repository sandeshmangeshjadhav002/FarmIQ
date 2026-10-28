"""Rate limiting tests (security hardening).

The limiter is a pure-ASGI token bucket (``app/rate_limit.py``). These tests
exercise it through a real HTTP stack, not by poking at internals, so the
bucket bookkeeping, the 429 shape and the middleware ordering are all covered.

The suite disables the limiter globally (see ``conftest.py``) because every
TestClient request comes from one synthetic address; these tests turn it back
on and, where they use the *shared* application instance, give each test its
own client address so bucket state cannot leak between tests.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import rate_limit
from app.config import get_settings


@pytest.fixture
def limited_app(monkeypatch):
    """A miniature app behind a fresh limiter, with the limiter forced on."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")
    get_settings.cache_clear()

    inner = FastAPI()

    @inner.get("/api/auth/login")
    def _login():
        return {"ok": True}

    @inner.get("/api/predictions/crop")
    def _predict():
        return {"ok": True}

    @inner.get("/api/farms")
    def _farms():
        return {"ok": True}

    @inner.get("/api/health")
    def _health():
        return {"ok": True}

    @inner.get("/api/health/ready")
    def _ready():
        return {"ok": True}

    inner.add_middleware(rate_limit.RateLimitMiddleware)

    with TestClient(inner) as client:
        yield client

    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────
# Path classification
# ─────────────────────────────────────────────────────────────────────────

def test_rule_for_path_classifies_each_endpoint_class():
    assert rate_limit.rule_for_path("/api/auth/login") is rate_limit.RULE_AUTH
    assert rate_limit.rule_for_path("/api/auth/register") is rate_limit.RULE_AUTH
    for heavy in ("/api/predictions/crop", "/api/chat", "/api/voice/speak", "/api/mlops/evaluation"):
        assert rate_limit.rule_for_path(heavy) is rate_limit.RULE_HEAVY, heavy
    assert rate_limit.rule_for_path("/api/farms") is rate_limit.RULE_DEFAULT


def test_rule_for_path_exempts_health_and_docs():
    for exempt in ("/", "/api/health", "/api/health/live", "/docs", "/redoc", "/openapi.json"):
        assert rate_limit.rule_for_path(exempt) is None, exempt


# ─────────────────────────────────────────────────────────────────────────
# Client identification
# ─────────────────────────────────────────────────────────────────────────

def _scope(client=("10.0.0.1", 1234), forwarded=None):
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return {"type": "http", "client": client, "headers": headers}


def test_client_key_uses_the_socket_address_by_default():
    assert rate_limit.client_key(_scope(forwarded="1.2.3.4"), False) == "10.0.0.1"


def test_client_key_uses_the_rightmost_forwarded_hop_when_trusted():
    # A client can prepend arbitrary values; only the hop appended by the
    # proxy (rightmost) is trustworthy.
    scope = _scope(forwarded="9.9.9.9, 203.0.113.7")
    assert rate_limit.client_key(scope, True) == "203.0.113.7"


def test_client_key_falls_back_to_the_socket_without_a_forwarded_header():
    assert rate_limit.client_key(_scope(), True) == "10.0.0.1"


# ─────────────────────────────────────────────────────────────────────────
# Enforcement
# ─────────────────────────────────────────────────────────────────────────

def test_auth_class_is_throttled_after_its_capacity(limited_app):
    capacity = rate_limit.RULE_AUTH.capacity
    for _ in range(capacity):
        assert limited_app.get("/api/auth/login").status_code == 200

    blocked = limited_app.get("/api/auth/login")
    assert blocked.status_code == 429
    body = blocked.json()
    assert "Too many requests" in body["detail"]
    assert body["limit_class"] == "auth"
    assert body["retry_after"] >= 1
    assert blocked.headers["Retry-After"] == str(body["retry_after"])


def test_each_endpoint_class_has_its_own_bucket(limited_app):
    """Exhausting the auth bucket must not affect unrelated endpoints."""
    for _ in range(rate_limit.RULE_AUTH.capacity):
        limited_app.get("/api/auth/login")
    assert limited_app.get("/api/auth/login").status_code == 429

    assert limited_app.get("/api/farms").status_code == 200
    assert limited_app.get("/api/predictions/crop").status_code == 200


def test_default_class_is_far_more_permissive_than_auth(limited_app):
    """A normal browsing burst must not be throttled by the auth policy."""
    for _ in range(rate_limit.RULE_AUTH.capacity + 1):
        assert limited_app.get("/api/farms").status_code == 200


def test_health_probes_are_never_throttled(limited_app):
    """Render polls the health path; a 429 there marks the service unhealthy."""
    for _ in range(rate_limit.RULE_HEAVY.capacity + 25):
        assert limited_app.get("/api/health").status_code == 200
        assert limited_app.get("/api/health/ready").status_code == 200


def test_limiter_passes_requests_through_when_disabled(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()

    inner = FastAPI()

    @inner.get("/api/auth/login")
    def _login():
        return {"ok": True}

    inner.add_middleware(rate_limit.RateLimitMiddleware)

    with TestClient(inner) as client:
        for _ in range(rate_limit.RULE_AUTH.capacity * 2):
            assert client.get("/api/auth/login").status_code == 200

    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────
# The bucket table stays bounded
# ─────────────────────────────────────────────────────────────────────────

def test_idle_buckets_are_evicted(monkeypatch):
    monkeypatch.setattr(rate_limit, "_MAX_BUCKETS", 0)
    monkeypatch.setattr(rate_limit, "_SWEEP_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(rate_limit, "_IDLE_EVICTION_SECONDS", 0.0)

    middleware = rate_limit.RateLimitMiddleware(lambda scope, receive, send: None)
    middleware._consume(("default", "1.1.1.1"), rate_limit.RULE_DEFAULT)
    middleware._consume(("default", "2.2.2.2"), rate_limit.RULE_DEFAULT)

    assert ("default", "1.1.1.1") not in middleware._buckets
    assert ("default", "2.2.2.2") in middleware._buckets


# ─────────────────────────────────────────────────────────────────────────
# Middleware ordering on the real application
# ─────────────────────────────────────────────────────────────────────────

def test_throttled_response_still_carries_cors_headers(monkeypatch):
    """A 429 must be readable by the browser, not reported as a CORS failure.

    CORSMiddleware is registered after the limiter, which makes it the
    outermost layer, so it decorates the 429 the limiter produces. If the
    order were ever reversed this test fails with a missing
    ``access-control-allow-origin`` header.
    """
    from app.main import app

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")
    get_settings.cache_clear()

    # A one-request bucket with an hourly refill. The real auth rule bursts up
    # to 10 and refills continuously, which makes the exact request that trips
    # it depend on wall-clock time; tightening the rule keeps this test
    # deterministic while still exercising the real middleware on the real app.
    monkeypatch.setattr(
        rate_limit, "RULE_AUTH", rate_limit.Rule("auth", capacity=1, refill_per_second=1 / 3600)
    )

    # A dedicated client address keeps this test's buckets away from any other
    # test that touches the shared application instance.
    origin = "http://localhost:5173"
    headers = {"Origin": origin}

    with TestClient(app, client=("198.51.100.7", 50000)) as client:
        allowed = client.post("/api/auth/login", json={}, headers=headers)
        assert allowed.status_code == 422, allowed.text
        assert allowed.headers.get("access-control-allow-origin") == origin

        blocked = client.post("/api/auth/login", json={}, headers=headers)
        assert blocked.status_code == 429, blocked.text
        assert blocked.headers.get("access-control-allow-origin") == origin
        assert blocked.headers.get("Retry-After")

    get_settings.cache_clear()
