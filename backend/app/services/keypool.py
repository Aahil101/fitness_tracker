"""Several API keys per provider, tried in turn when one stops working.

The app previously held one key per provider, which made every AI feature depend
on a single credential staying healthy. In practice it does not: Gemini's free
tier allows twenty calls a day, a project can be suspended, a key can be revoked,
and a model can be withdrawn for one project while remaining available to another.
Any of those took the whole feature down until someone noticed and edited an
environment variable.

So keys are now a pool. A call takes the first healthy key; if that key comes back
with a quota, auth or permission error, the key is benched and the call is retried
on the next one. A key is benched rather than dropped because most of these
failures are temporary — a daily quota resets, a 503 passes.

Two things this deliberately does not do. It does not retry a request that was
itself wrong: a malformed prompt fails identically on every key, so retrying six
times just wastes six keys. And it does not treat exhausting the pool as anything
other than the provider being unavailable, so the caller's existing fallback
behaviour still applies.

A note on quotas. Spreading load across several free-tier keys raises the number
of calls the app can make per day, and for Google's API that is against the terms
of the free tier, which are set per project rather than per key. Failover across
keys you own is a reasonable thing to want for resilience; relying on it to serve
customers is not a foundation that holds. The durable answer is billing on one
project, which for this workload costs very little.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: How long a key sits out after a quota refusal. A daily quota will not have
#: reset, but re-checking hourly costs one wasted call and keeps recovery
#: automatic rather than requiring a deploy.
QUOTA_COOLDOWN_S = 60 * 60

#: A shorter bench for transient trouble: overload, timeout, a 5xx.
TRANSIENT_COOLDOWN_S = 60

#: Auth and permission failures are not going to fix themselves, so the key sits
#: out for a long time rather than being retried on every request.
AUTH_COOLDOWN_S = 6 * 60 * 60


@dataclass
class _Key:
    value: str
    #: Monotonic time before which this key should not be used.
    benched_until: float = 0.0
    failures: int = 0
    successes: int = 0

    @property
    def label(self) -> str:
        """Enough to identify it in a log without writing the key down."""
        return f"{self.value[:6]}…{self.value[-4:]}"


@dataclass
class KeyPool:
    """Keys for one provider, with health tracked per key."""

    name: str
    keys: list[_Key] = field(default_factory=list)
    _cursor: int = 0

    @classmethod
    def from_values(cls, name: str, values: list[str]) -> KeyPool:
        seen: set[str] = set()
        unique: list[_Key] = []
        for value in values:
            cleaned = (value or "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                unique.append(_Key(value=cleaned))
        return cls(name=name, keys=unique)

    def __bool__(self) -> bool:
        return bool(self.keys)

    @property
    def size(self) -> int:
        return len(self.keys)

    @property
    def available(self) -> int:
        now = time.monotonic()
        return sum(1 for key in self.keys if key.benched_until <= now)

    def healthy(self) -> list[_Key]:
        """Usable keys, starting after the last one used.

        Rotating the starting point spreads load instead of hammering the first
        key until it hits its quota and only then moving on. Benched keys are
        appended so that a pool where everything is benched still returns
        something to try — better one hopeful call than a certain failure.
        """
        if not self.keys:
            return []
        now = time.monotonic()
        order = self.keys[self._cursor :] + self.keys[: self._cursor]
        ready = [key for key in order if key.benched_until <= now]
        benched = [key for key in order if key.benched_until > now]
        return ready + benched

    def note_success(self, key: _Key) -> None:
        key.successes += 1
        key.benched_until = 0.0
        if key in self.keys:
            self._cursor = (self.keys.index(key) + 1) % len(self.keys)

    def bench(self, key: _Key, reason: str, seconds: float) -> None:
        key.failures += 1
        key.benched_until = time.monotonic() + seconds
        log.info(
            "%s key %s benched for %.0f min (%s); %d of %d still available",
            self.name,
            key.label,
            seconds / 60,
            reason,
            self.available,
            self.size,
        )

    def status(self) -> dict[str, Any]:
        """For the diagnostics endpoint. Never includes a key."""
        now = time.monotonic()
        return {
            "provider": self.name,
            "keys": self.size,
            "available": self.available,
            "detail": [
                {
                    "key": key.label,
                    "state": "ready" if key.benched_until <= now else "benched",
                    "benched_for_s": max(0, round(key.benched_until - now)),
                    "successes": key.successes,
                    "failures": key.failures,
                }
                for key in self.keys
            ],
        }


def classify(status_code: int | None, message: str) -> tuple[str, float] | None:
    """How long to bench a key for, given how the call failed.

    Returns ``(reason, seconds)``, or None when the failure is the request's fault
    and no key would have done better.
    """
    text = (message or "").lower()

    if status_code in (401, 403) or "api key" in text or "permission" in text:
        return "auth or permission refused", AUTH_COOLDOWN_S
    if status_code == 429 or "quota" in text or "rate limit" in text:
        return "quota reached", QUOTA_COOLDOWN_S
    if status_code == 404 and ("no longer available" in text or "not have access" in text):
        # The model is withdrawn for this project but may exist for others.
        return "model unavailable to this project", AUTH_COOLDOWN_S
    if status_code is not None and status_code >= 500:
        return "provider error", TRANSIENT_COOLDOWN_S
    if "overload" in text or "high demand" in text or "unavailable" in text:
        return "provider overloaded", TRANSIENT_COOLDOWN_S
    if "timed out" in text or "timeout" in text:
        return "timed out", TRANSIENT_COOLDOWN_S
    return None


# ---------------------------------------------------------------------------
# Pool registry
#
# Pools hold health state, so they have to outlive a request. Keyed by provider
# and rebuilt only when the configured keys actually change, so editing an
# environment variable takes effect without losing the health of keys that stayed.
# ---------------------------------------------------------------------------
_POOLS: dict[str, KeyPool] = {}


def get_pool(name: str, values: list[str]) -> KeyPool:
    existing = _POOLS.get(name)
    if existing is not None and [key.value for key in existing.keys] == [
        v.strip() for v in values if v.strip()
    ]:
        return existing
    pool = KeyPool.from_values(name, values)
    _POOLS[name] = pool
    log.info("%s key pool built with %d key(s)", name, pool.size)
    return pool


def all_status() -> list[dict[str, Any]]:
    return [pool.status() for pool in _POOLS.values()]
