"""analysis/fundamentals/cache.py — a tiny thread-safe TTL cache.

Used in two layers:
  * raw provider responses  (inside YahooFundamentalProvider)
  * normalized CompanyFundamentals (inside FundamentalsService)

Both default to a 24-hour TTL (fundamentals change at most quarterly). Cache hits and
misses are logged so the data path is observable. Process-local (in-memory) — sufficient
for a single Streamlit server; swap for Redis later behind the same get/set interface.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

_log = logging.getLogger("fundamentals.cache")

DEFAULT_TTL_SECONDS = 24 * 60 * 60


class TTLCache:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, name: str = "cache"):
        self.ttl = ttl_seconds
        self.name = name
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value, or None on a miss / expiry (logged)."""
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                _log.info("cache MISS [%s] key=%s", self.name, key)
                return None
            expires_at, value = entry
            if now >= expires_at:
                # expired — evict and treat as a miss
                del self._store[key]
                self.misses += 1
                _log.info("cache MISS [%s] key=%s (expired)", self.name, key)
                return None
            self.hits += 1
            _log.info("cache HIT  [%s] key=%s", self.name, key)
            return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = self.ttl if ttl_seconds is None else ttl_seconds
        with self._lock:
            self._store[key] = (time.time() + ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = self.misses = 0

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"name": self.name, "size": len(self._store), "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0}
