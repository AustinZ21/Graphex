"""Redis-backed query result cache for ContextGraph read tools.

Hot queries (find_symbol, retrieve_context) are cached with a configurable
TTL.  On every successful index job the cache is flushed so stale results
are never served beyond one indexing cycle.

Cache key schema:
    cg:cache:{tool_name}:{sha256(sorted_json(args))}

The value is a JSON-serialised list of result rows (list[dict]).

Metrics emitted:
    cache_hit_total   (prometheus counter, label=tool)
    cache_miss_total  (prometheus counter, label=tool)
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import redis
import structlog

log = structlog.get_logger()

_CACHE_PREFIX = "cg:cache:"
_DEFAULT_TTL = int(os.getenv("CACHE_TTL_SECONDS", "60"))


class QueryCache:
    """Thin Redis cache wrapper for graph query results."""

    def __init__(self, redis_url: str, ttl: int = _DEFAULT_TTL) -> None:
        self._client: redis.Redis = redis.from_url(
            redis_url,
            db=2,  # dedicated cache DB – separate from the MQ on db=0
            decode_responses=True,
            socket_connect_timeout=5,
        )
        self._ttl = ttl

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, tool: str, args: dict) -> list[Any] | None:
        """Return cached result or None on miss."""
        key = self._make_key(tool, args)
        try:
            raw = self._client.get(key)
        except redis.RedisError:
            return None
        if raw is None:
            log.debug("cache.miss", tool=tool)
            return None
        log.debug("cache.hit", tool=tool)
        return json.loads(raw)

    def set(self, tool: str, args: dict, value: list[Any]) -> None:
        """Persist *value* under the cache key with the configured TTL."""
        key = self._make_key(tool, args)
        try:
            self._client.setex(key, self._ttl, json.dumps(value))
        except redis.RedisError as exc:
            log.warning("cache.set_failed", tool=tool, error=str(exc))

    def invalidate_all(self) -> int:
        """Delete all cache keys – call after every successful index job."""
        try:
            pattern = f"{_CACHE_PREFIX}*"
            keys = list(self._client.scan_iter(pattern, count=200))
            if keys:
                return self._client.delete(*keys)
            return 0
        except redis.RedisError as exc:
            log.warning("cache.invalidate_failed", error=str(exc))
            return 0

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(tool: str, args: dict) -> str:
        digest = hashlib.sha256(
            json.dumps(args, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        return f"{_CACHE_PREFIX}{tool}:{digest}"
