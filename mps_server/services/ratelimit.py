"""In-process sliding-window rate limiter (V-H5).

Protects authentication from brute force and from account-lock denial of
service. Keying login attempts by client IP throttles an attacker before they
can drive any single account into lockout, and keying by username bounds
credential-stuffing against a known account.

This is a single-process limiter suitable for the single-site pilot. A
multi-process or multi-site deployment should additionally enforce limits at a
shared gateway (the application limit is defence in depth, not a replacement).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded; retry after {retry_after}s")


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record an attempt for key; raise RateLimitExceeded if over the limit."""
        now = time.monotonic()
        with self._lock:
            q = self._events[key]
            cutoff = now - self.window
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.max_events:
                retry_after = int(self.window - (now - q[0])) + 1
                raise RateLimitExceeded(retry_after)
            q.append(now)

    def reset(self, key: str) -> None:
        """Clear a key's history (e.g. after a successful login)."""
        with self._lock:
            self._events.pop(key, None)


# Login limiters. Generous enough for genuine users, tight enough to stop
# brute force and account-lock abuse. Tune via env if needed.
import os

_PER_IP_MAX = int(os.getenv("LOGIN_RATE_IP_MAX", "20"))
_PER_USER_MAX = int(os.getenv("LOGIN_RATE_USER_MAX", "10"))
_WINDOW = float(os.getenv("LOGIN_RATE_WINDOW_SECONDS", "300"))

login_ip_limiter = SlidingWindowLimiter(_PER_IP_MAX, _WINDOW)
login_user_limiter = SlidingWindowLimiter(_PER_USER_MAX, _WINDOW)
