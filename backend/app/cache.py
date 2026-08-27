"""Upstash Redis (REST) cache + fixed-window rate limiter.

Upstash is optional. When it is not configured we fall back to a process-local
dict so local development and tests work unchanged. The fallback is per-process,
which is fine at this scale but is *not* a substitute in a multi-instance deploy —
set the Upstash env vars there.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings
from .http import get_http_client

log = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    limit: int
    reset_in_s: int


class _MemoryStore:
    """Minimal TTL store used when Upstash is not configured."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[float | None, str]] = {}
        self._counters: dict[str, tuple[float, int]] = {}

    def get(self, key: str) -> str | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at is not None and expires_at < time.time():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_s: int | None) -> None:
        expires_at = time.time() + ttl_s if ttl_s else None
        self._values[key] = (expires_at, value)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)

    def incr(self, key: str, window_s: int) -> tuple[int, int]:
        now = time.time()
        expires_at, count = self._counters.get(key, (0.0, 0))
        if expires_at < now:
            expires_at, count = now + window_s, 0
        count += 1
        self._counters[key] = (expires_at, count)
        return count, max(1, int(expires_at - now))


_memory = _MemoryStore()


async def _command(*args: Any) -> Any:
    """Execute a single Redis command through the Upstash REST endpoint."""
    if not settings.redis_configured:
        return None
    client = get_http_client()
    try:
        resp = await client.post(
            settings.upstash_redis_rest_url,
            json=[str(a) for a in args],
            headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}"},
        )
    except httpx.HTTPError as exc:
        log.warning("Redis command failed (%s): %s", args[0], exc)
        return None
    if resp.status_code >= 400:
        log.warning("Redis rejected %s: %s %s", args[0], resp.status_code, resp.text[:200])
        return None
    try:
        return resp.json().get("result")
    except ValueError:
        return None


async def cache_get_json(key: str) -> Any | None:
    if settings.redis_configured:
        raw = await _command("GET", key)
    else:
        raw = _memory.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def cache_set_json(key: str, value: Any, ttl_s: int = 3600) -> None:
    raw = json.dumps(value, default=str)
    if settings.redis_configured:
        await _command("SET", key, raw, "EX", ttl_s)
    else:
        _memory.set(key, raw, ttl_s)


async def cache_delete(key: str) -> None:
    if settings.redis_configured:
        await _command("DEL", key)
    else:
        _memory.delete(key)


async def check_rate_limit(bucket: str, identifier: str, limit: int, window_s: int = 3600) -> RateLimitResult:
    """Fixed-window counter. Cheap, predictable, good enough for a private app."""
    key = f"rl:{bucket}:{identifier}:{int(time.time() // window_s)}"

    if settings.redis_configured:
        count = await _command("INCR", key)
        if count is None:  # Redis unreachable — fail open rather than lock users out
            return RateLimitResult(True, limit, limit, window_s)
        count = int(count)
        if count == 1:
            await _command("EXPIRE", key, window_s)
        reset_in = window_s - int(time.time() % window_s)
    else:
        count, reset_in = _memory.incr(key, window_s)

    return RateLimitResult(
        allowed=count <= limit,
        remaining=max(0, limit - count),
        limit=limit,
        reset_in_s=reset_in,
    )
