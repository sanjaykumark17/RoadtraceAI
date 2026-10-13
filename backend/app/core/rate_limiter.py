"""
In-memory sliding-window rate limiter for sensitive authentication endpoints.
Protects /api/v1/auth/login and /api/v1/auth/refresh against brute-force attacks.
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
            timestamps = self._requests[client_key]
            # Prune timestamps older than the sliding window
            self._requests[client_key] = [t for t in timestamps if t > cutoff]

            if len(self._requests[client_key]) >= max_requests:
                return False

            self._requests[client_key].append(now)
            return True

    def reset(self):
        with self._lock:
            self._requests.clear()


auth_limiter = InMemoryRateLimiter()


async def check_auth_rate_limit(request: Request):
    """
    FastAPI dependency enforcing request throttling on authentication endpoints.
    Identifies clients by X-Forwarded-For header or direct client IP.
    """
    if not settings.auth_rate_limit_enabled:
        return

    # Extract client IP (handle reverse proxies like Nginx, Render, AWS ALB)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    elif request.client:
        client_ip = request.client.host
    else:
        client_ip = "unknown_client"

    max_reqs = settings.auth_rate_limit_per_minute
    if not auth_limiter.is_allowed(client_ip, max_requests=max_reqs, window_seconds=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication requests. Please try again later.",
            headers={"Retry-After": "60"},
        )
