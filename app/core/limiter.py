"""Tiny in-memory rate limiter (sliding window), keyed by client IP.

Good enough for one server process. If you deploy several workers or servers, each keeps
its own counters: switch to Redis (or slowapi + Redis) then. Behind a reverse proxy,
request.client.host is the proxy's address, so configure proxy headers before relying on it.

Usage:  dependencies=[Depends(RateLimiter(times=10, seconds=60, scope="login"))]
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import settings

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


class RateLimiter:
    def __init__(self, times: int, seconds: int, scope: str):
        self.times = times
        self.seconds = seconds
        self.scope = scope

    def __call__(self, request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        ip = request.client.host if request.client else "unknown"
        key = f"{self.scope}:{ip}"
        now = time.monotonic()
        with _lock:
            hits = _hits[key]
            while hits and now - hits[0] > self.seconds:
                hits.popleft()
            if len(hits) >= self.times:
                retry_after = int(self.seconds - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please slow down.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()