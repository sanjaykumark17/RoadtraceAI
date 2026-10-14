"""
In-memory sliding-window rate limiter for sensitive authentication and API endpoints.
Protects auth endpoints, /search and /trajectory against brute-force and excessive load.
"""

from collections import defaultdict
from datetime import datetime, timezone
import threading
from typing import Dict, List

from fastapi import HTTPException, Request, status

from app.core.config import settings


class InMemoryRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, client_key: str, max_requests: int, window_seconds: int = 60) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - window_seconds

        with self._lock:
            # Evict stale keys across dictionary
            stale_keys = [k for k, v in self._requests.items() if not v or v[-1] <= cutoff]
            for k in stale_keys:
                if k != client_key:
                    del self._requests[k]

            timestamps = self._requests[client_key]
            # Prune timestamps older than sliding window
            valid_timestamps = [t for t in timestamps if t > cutoff]

            if len(valid_timestamps) >= max_requests:
                self._requests[client_key] = valid_timestamps
                return False

            valid_timestamps.append(now)
            self._requests[client_key] = valid_timestamps
            return True

    def reset(self):
        with self._lock:
            self._requests.clear()


auth_limiter = InMemoryRateLimiter()
api_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP, trusting X-Forwarded-For only from configured trusted proxies."""
    direct_ip = request.client.host if request.client else ""
    if direct_ip in settings.trusted_proxies:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return direct_ip or "unknown_client"


async def check_auth_rate_limit(request: Request):
    """FastAPI dependency enforcing request throttling on authentication endpoints."""
    if not settings.auth_rate_limit_enabled:
        return

    client_ip = get_client_ip(request)
    max_reqs = settings.auth_rate_limit_per_minute
    if not auth_limiter.is_allowed(client_ip, max_requests=max_reqs, window_seconds=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication requests. Please try again later.",
            headers={"Retry-After": "60"},
        )


async def check_api_rate_limit(request: Request):
    """FastAPI dependency enforcing rate limiting on search and trajectory endpoints."""
    if not settings.auth_rate_limit_enabled:
        return

    client_ip = get_client_ip(request)
    max_reqs = settings.api_rate_limit_per_minute
    if not api_limiter.is_allowed(client_ip, max_requests=max_reqs, window_seconds=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": "60"},
        )

