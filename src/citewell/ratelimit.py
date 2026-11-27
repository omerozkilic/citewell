"""In-memory sliding-window rate limiter for the HTTP server (per process)."""

import threading
import time
from collections import deque
from collections.abc import Callable

WINDOW_SECONDS = 60.0
PRUNE_ABOVE = 1024  # keys; only matters when anonymous clients are keyed by IP address


class RateLimiter:
    """Allow at most ``limit`` requests per key in any 60 s window; ``limit`` 0 disables it."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic):
        self.limit = max(0, limit)
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Record a request. Returns ``None`` if allowed, else seconds until a slot frees up."""
        if not self.limit:
            return None
        now = self._clock()
        cutoff = now - WINDOW_SECONDS
        with self._lock:
            if len(self._hits) > PRUNE_ABOVE:
                self._prune(cutoff)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.0, hits[0] + WINDOW_SECONDS - now)
            hits.append(now)
            return None

    def _prune(self, cutoff: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or h[-1] <= cutoff]:
            del self._hits[key]
