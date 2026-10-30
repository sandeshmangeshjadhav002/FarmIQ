"""A tiny in-process TTL cache.

Why not ``functools.lru_cache``: the AI agent re-uses expensive, *time-sensitive*
results (a weather report, a farm-context snapshot) where an entry must expire
after a short window. ``lru_cache`` has no notion of time and would serve a
weather report from hours ago.

Design notes
------------
* **Thread-safe.** FastAPI runs sync endpoints in a threadpool, so several
  requests can touch the cache at once.
* **The lock is never held while ``factory`` runs.** A slow network lookup in
  :meth:`TTLCache.get_or_set` therefore cannot block unrelated keys. Two
  concurrent misses may both call the factory — acceptable here because every
  factory is an idempotent read (the only cost is one extra call, never wrong
  data).
* **Bounded.** Expired entries are dropped on write; if the cache is still
  full, the entry closest to expiry is evicted. Nothing is fabricated or
  persisted — this is a cache, not a store.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable, Optional


class TTLCache:
    """A small, bounded, thread-safe cache whose entries expire after ``ttl``."""

    def __init__(self, ttl_seconds: float, maxsize: int = 256):
        self._ttl = float(ttl_seconds)
        self._maxsize = max(1, int(maxsize))
        self._lock = threading.Lock()
        self._store: dict[Hashable, tuple[float, Any]] = {}

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return default
            expires_at, value = item
            if expires_at < time.monotonic():
                self._store.pop(key, None)
                return default
            return value

    def set(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        ttl = self._ttl if ttl is None else float(ttl)
        expires_at = time.monotonic() + ttl
        with self._lock:
            if key not in self._store and len(self._store) >= self._maxsize:
                self._evict_locked()
            self._store[key] = (expires_at, value)

    def get_or_set(
        self, key: Hashable, factory: Callable[[], Any], ttl: Optional[float] = None
    ) -> Any:
        """Return the cached value, computing and storing it on a miss."""
        sentinel = _MISS
        hit = self.get(key, sentinel)
        if hit is not sentinel:
            return hit
        value = factory()
        self.set(key, value, ttl=ttl)
        return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def _evict_locked(self) -> None:
        """Drop expired entries, then the soonest-to-expire one. Lock held."""
        now = time.monotonic()
        for key in [k for k, (exp, _) in self._store.items() if exp < now]:
            self._store.pop(key, None)
        if len(self._store) >= self._maxsize and self._store:
            soonest = min(self._store.items(), key=lambda kv: kv[1][0])[0]
            self._store.pop(soonest, None)


_MISS = object()
