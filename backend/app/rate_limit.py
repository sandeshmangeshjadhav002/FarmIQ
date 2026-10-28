"""Dependency-free, in-process rate limiting.

Why hand-rolled?
----------------
``slowapi``/``limits`` would be the obvious choice, but a correct multi-process
deployment needs a shared store (Redis) — an extra paid dependency this project
does not have. The backend runs as a **single** uvicorn worker per instance on
Render, so a per-process token bucket is the honest, correctly-scoped choice.
If the service is ever scaled past one instance this must be revisited (the
limiter is per-process, so the effective limit becomes ``N × configured``).

Algorithm
---------
One token bucket per ``(rule, client)`` pair. A bucket refills continuously at
``refill_per_second`` up to ``capacity``; each request spends one token. An
empty bucket yields HTTP 429 with a ``Retry-After`` header so well-behaved
clients back off instead of hammering.

Endpoint classes
----------------
Buckets are keyed by endpoint *class* rather than exact path, so the strictest
limit applies exactly where it matters (credential stuffing, unbounded model
inference, third-party quota exhaustion) without punishing normal browsing.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import get_settings

logger = logging.getLogger("farmiq.ratelimit")

# ── Endpoint classes ──────────────────────────────────────────────────────
# Credential endpoints: strict, to blunt password guessing against a real user.
_STRICT_PREFIXES = ("/api/auth/",)
# Endpoints that run model inference, RAG/LLM calls, or third-party requests.
_HEAVY_PREFIXES = ("/api/predictions", "/api/chat", "/api/voice", "/api/mlops")
# Monitoring/probe endpoints must never be throttled: Render polls the health
# check path and a 429 there would make the platform mark the service unhealthy.
_EXEMPT_PREFIXES = ("/api/health", "/docs", "/redoc", "/openapi.json")


@dataclass(frozen=True)
class Rule:
    """A token bucket definition."""

    name: str
    capacity: int
    refill_per_second: float


RULE_AUTH = Rule("auth", capacity=10, refill_per_second=10 / 60)
RULE_HEAVY = Rule("heavy", capacity=40, refill_per_second=40 / 60)
RULE_DEFAULT = Rule("default", capacity=200, refill_per_second=200 / 60)

# Bound memory: buckets idle longer than this are evicted during a sweep.
_IDLE_EVICTION_SECONDS = 600.0
_MAX_BUCKETS = 10_000
_SWEEP_INTERVAL_SECONDS = 60.0


def rule_for_path(path: str) -> Optional[Rule]:
    """Return the rule governing ``path``, or ``None`` when it is exempt."""
    if path == "/" or path.startswith(_EXEMPT_PREFIXES):
        return None
    if path.startswith(_STRICT_PREFIXES):
        return RULE_AUTH
    if path.startswith(_HEAVY_PREFIXES):
        return RULE_HEAVY
    return RULE_DEFAULT


@dataclass
class _Bucket:
    tokens: float
    updated: float


def _headers_to_dict(raw_headers: list) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in raw_headers
    }


def client_key(scope: Scope, trust_proxy: bool) -> str:
    """Identify the caller for bucket purposes.

    Behind Render (or any reverse proxy) ``scope["client"]`` is the proxy's
    address, so every user would share one bucket. The proxy appends the
    connecting address to the **right** of ``X-Forwarded-For``; that rightmost
    entry is the one a client cannot forge, so it is used when
    ``TRUST_PROXY_HEADERS`` is enabled. It is off by default because trusting a
    client-supplied header on a directly-exposed server lets anyone bypass the
    limit by rotating the header value.
    """
    if trust_proxy:
        forwarded = _headers_to_dict(scope.get("headers") or []).get("x-forwarded-for")
        if forwarded:
            hops = [part.strip() for part in forwarded.split(",") if part.strip()]
            if hops:
                return hops[-1]
    client = scope.get("client")
    if client:
        return client[0]
    return "unknown"


class RateLimitMiddleware:
    """Pure-ASGI token-bucket limiter (no ``BaseHTTPMiddleware`` overhead).

    Must be added to the application **before** ``CORSMiddleware`` so that CORS
    is the outermost layer — otherwise a throttled response would be missing
    the CORS headers and the browser would report a network/CORS failure
    instead of surfacing the 429 to the application.
    """

    def __init__(self, app: ASGIApp):
        self.app = app
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    # ── bucket bookkeeping ────────────────────────────────────────────────
    def _consume(self, key: tuple[str, str], rule: Rule) -> Optional[float]:
        """Spend one token. Return ``None`` on success, else seconds to wait."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(rule.capacity), updated=now)
                self._buckets[key] = bucket
            else:
                elapsed = now - bucket.updated
                if elapsed > 0:
                    bucket.tokens = min(
                        float(rule.capacity),
                        bucket.tokens + elapsed * rule.refill_per_second,
                    )
                    bucket.updated = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                self._maybe_sweep(now)
                return None

            deficit = 1.0 - bucket.tokens
            return deficit / rule.refill_per_second

    def _maybe_sweep(self, now: float) -> None:
        """Drop stale buckets so the table cannot grow without bound."""
        if len(self._buckets) <= _MAX_BUCKETS:
            return
        if now - self._last_sweep < _SWEEP_INTERVAL_SECONDS:
            return
        cutoff = now - _IDLE_EVICTION_SECONDS
        stale = [k for k, b in self._buckets.items() if b.updated < cutoff]
        for key in stale:
            del self._buckets[key]
        self._last_sweep = now

    def reset(self) -> None:
        """Clear all buckets (used by tests)."""
        with self._lock:
            self._buckets.clear()

    # ── ASGI entrypoint ───────────────────────────────────────────────────
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        if not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        rule = rule_for_path(scope.get("path", ""))
        if rule is None:
            await self.app(scope, receive, send)
            return

        key = (rule.name, client_key(scope, settings.trust_proxy_headers))
        retry_after = self._consume(key, rule)
        if retry_after is None:
            await self.app(scope, receive, send)
            return

        wait_seconds = max(1, math.ceil(retry_after))
        logger.warning(
            "Rate limit exceeded: rule=%s path=%s retry_after=%ss",
            rule.name,
            scope.get("path"),
            wait_seconds,
        )
        response = JSONResponse(
            status_code=429,
            content={
                "detail": (
                    "Too many requests. Please slow down and try again in "
                    f"{wait_seconds} second(s)."
                ),
                "retry_after": wait_seconds,
                "limit_class": rule.name,
            },
            headers={"Retry-After": str(wait_seconds)},
        )
        await response(scope, receive, send)
