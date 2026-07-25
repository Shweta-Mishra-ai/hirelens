"""
HireLens — Shared Rate Limiting Helper

Generic Redis-backed fixed-window rate limiter. Used for:
- Per-IP brute-force protection on /auth/login and /auth/signup
  (these happen BEFORE a user is authenticated, so the per-user limiter
  in analysis.py doesn't apply to them)
- Any other endpoint that needs a simple "N requests per window" guard

Fails OPEN (allows the request) if Redis is unavailable — matches the
rest of the app's degrade-gracefully philosophy. Rate limiting is a
defense-in-depth measure, not the only line of defense, so an outage
here shouldn't take down login for everyone.
"""

import time
import logging
from fastapi import Request
from app.core.exceptions import RateLimitExceeded

logger = logging.getLogger("hirelens")


_mem_rate_limit: dict[str, list[float]] = {}


def _check_in_memory_rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    now = time.time()
    cutoff = now - window_seconds
    timestamps = _mem_rate_limit.get(key, [])
    valid_ts = [t for t in timestamps if t > cutoff]
    if len(valid_ts) >= limit:
        raise RateLimitExceeded(retry_after=window_seconds)
    valid_ts.append(now)
    _mem_rate_limit[key] = valid_ts
    
    # Bounded cleanup if memory store grows
    if len(_mem_rate_limit) > 2000:
        stale = [k for k, v in _mem_rate_limit.items() if not any(t > cutoff for t in v)]
        for k in stale:
            _mem_rate_limit.pop(k, None)


def get_client_ip(request: Request) -> str:
    """Best-effort real client IP behind a proxy (Render/Vercel set X-Forwarded-For)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(redis, key: str, limit: int, window_seconds: int = 60) -> None:
    """Raises RateLimitExceeded if `key` has been hit more than `limit` times
    within the current window. Uses Redis when configured, falling back to in-memory."""
    if not redis:
        _check_in_memory_rate_limit(key, limit, window_seconds)
        return
    try:
        bucket = int(time.time()) // window_seconds
        redis_key = f"rl:{key}:{bucket}"
        count = redis.incr(redis_key)
        if count == 1:
            redis.expire(redis_key, window_seconds)
        if count > limit:
            raise RateLimitExceeded(retry_after=window_seconds)
    except RateLimitExceeded:
        raise
    except Exception as e:
        logger.warning(f"Redis rate limit check failed for '{key}' (falling back to memory): {e}")
        _check_in_memory_rate_limit(key, limit, window_seconds)
