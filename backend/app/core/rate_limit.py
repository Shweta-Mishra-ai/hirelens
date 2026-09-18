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

import ipaddress
import time
import logging
from fastapi import Request
from app.core.config import settings
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


def _looks_like_an_address(value: str) -> bool:
    """Reject anything that is not an IP, so a junk header cannot poison the key."""
    try:
        ipaddress.ip_address(value.strip("[]"))
        return True
    except ValueError:
        return False


def get_client_ip(request: Request) -> str:
    """
    The caller's address, as far as it can be trusted.

    X-Forwarded-For is written by proxies AND by the caller: each proxy
    appends the address it saw, so the rightmost entries are the ones added by
    infrastructure and everything to the left is whatever the caller chose to
    send. Only `TRUSTED_PROXY_HOPS` entries from the right are evidence.

    This matters because rate limits are keyed on the result. Reading the
    leftmost entry lets a caller mint a fresh bucket per request by changing a
    header — which is unlimited password guesses against sign-in, and
    unlimited account creation.
    """
    direct = request.client.host if request.client else "unknown"

    hops = getattr(settings, "TRUSTED_PROXY_HOPS", 1)
    if hops <= 0:
        # Nothing proxies this app, so the header is not evidence of anything.
        return direct

    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return direct

    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if not parts:
        return direct

    # Count in from the right: parts[-hops] is the address the outermost
    # trusted proxy actually observed.
    candidate = parts[-hops] if len(parts) >= hops else parts[0]
    return candidate if _looks_like_an_address(candidate) else direct


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
