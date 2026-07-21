"""Small bounded in-process rate limiter for abuse-sensitive endpoints."""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import math
import threading
import time
from typing import Callable

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int
    remaining: int


@dataclass
class _Entry:
    timestamps: deque[float]
    expires_at: float


class SlidingWindowRateLimiter:
    """Thread-safe sliding window with bounded client/scope cardinality.

    Expired entries are removed on every check. If all slots are still active,
    a new client is denied rather than evicting an active entry and allowing a
    cardinality flood to reset an attacker's own limit.
    """

    def __init__(
        self,
        *,
        max_entries: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = int(max_entries)
        self._clock = clock
        self._entries: OrderedDict[tuple[str, str], _Entry] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    def _cleanup(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)

    def check(
        self,
        *,
        scope: str,
        client: str,
        limit: int,
        window_seconds: float,
    ) -> RateLimitResult:
        if not scope:
            raise ValueError("scope is required")
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")

        key = (str(scope), str(client or "unknown"))
        now = float(self._clock())
        window = float(window_seconds)
        cutoff = now - window
        with self._lock:
            self._cleanup(now)
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self._max_entries:
                    earliest_expiry = min(item.expires_at for item in self._entries.values())
                    retry = max(1, math.ceil(earliest_expiry - now))
                    return RateLimitResult(False, retry, 0)
                entry = _Entry(deque(), now + window)
                self._entries[key] = entry
            else:
                self._entries.move_to_end(key)

            while entry.timestamps and entry.timestamps[0] <= cutoff:
                entry.timestamps.popleft()
            if len(entry.timestamps) >= limit:
                retry = max(1, math.ceil(entry.timestamps[0] + window - now))
                return RateLimitResult(False, retry, 0)

            entry.timestamps.append(now)
            entry.expires_at = now + window
            return RateLimitResult(True, 0, max(0, limit - len(entry.timestamps)))


RATE_LIMITER = SlidingWindowRateLimiter()


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    limit: int,
    window_seconds: float,
    limiter: SlidingWindowRateLimiter = RATE_LIMITER,
) -> None:
    """Raise HTTP 429 using the ASGI client identity only.

    ``Request.client`` is populated by the server (and, when configured, its
    trusted proxy middleware). Arbitrary forwarding headers are intentionally
    ignored here.
    """
    client = request.client.host if request.client else "unknown"
    result = limiter.check(
        scope=scope,
        client=client,
        limit=limit,
        window_seconds=window_seconds,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="請求過於頻繁，請稍後再試",
            headers={"Retry-After": str(result.retry_after)},
        )
