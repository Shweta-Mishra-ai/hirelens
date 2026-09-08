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
import ipaddress
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


def _is_routable_public_ip(value: str) -> bool:
    """True only for a real, globally-routable client address.

    Entries that are private (10./172.16./192.168.), loopback, link-local or
    not a valid IP at all are internal hops or junk — never the client we
    want to rate-limit by.
    """
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def get_client_ip(request: Request) -> str:
    """
    Real client IP behind a reverse proxy (Render/Vercel set X-Forwarded-For).

    This used to return `xff.split(",")[0]` — the LEFTMOST entry. That is the
    one value in the header an attacker fully controls: a proxy *appends* to
    X-Forwarded-For rather than replacing it, so whatever the client sent
    survives at the front of the list. Since this function is what keys the
    per-IP brute-force limiter on /auth/login, /auth/signup and
    /auth/forgot-password, a caller could defeat rate limiting entirely by
    sending a different fake `X-Forwarded-For: 1.2.3.4` on every attempt:
    every request lands in a fresh bucket, so the limit never trips and an
    unlimited password-guessing run is free.

    The trustworthy end is the RIGHT: the last entry was appended by our own
    edge proxy and reflects the peer it actually saw. So walk from the right
    and take the first globally-routable address — skipping internal hops,
    which would otherwise collapse every user into one shared bucket and rate
    limit them all together. A client can prepend anything it likes; it
    cannot append past our own edge.

    Set TRUST_PROXY_HEADERS=false when the app is exposed directly with no
    proxy in front. There, X-Forwarded-For carries no trustworthy value at
    all and must be ignored rather than believed.
    """
    if settings.TRUST_PROXY_HEADERS:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            for candidate in reversed(parts):
                if _is_routable_public_ip(candidate):
                    return candidate
            if parts:
                # Everything in the chain is internal (typical for local or
                # in-cluster traffic). The rightmost is still the closest to
                # the truth; the leftmost is still the most forgeable.
                return parts[-1]
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
