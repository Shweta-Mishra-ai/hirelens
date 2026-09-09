"""
HireLens — Cache helper

Thin JSON cache over the same Redis client used for rate limiting
(app.core.dependencies.get_redis). Two things were previously being
recomputed/refetched from scratch on every single request with no cache
layer at all:

1. GitHub verification (`/verify/{id}/run`) — hits the live GitHub API for
   profile + repo list + per-repo language breakdown on every run, even
   when re-verifying the same candidate a minute later, or when two
   recruiters on the same team check the same public GitHub username.
   That's expensive against GitHub's 60/hr (unauthenticated) or 5000/hr
   (with GITHUB_TOKEN) rate limit for data that doesn't change minute to
   minute.
2. Talent analytics (`/reports/analytics`) — recomputes score distribution,
   top skills, and risk categories from every report row on every single
   dashboard page load.

Both get a short TTL cache here. Redis being unavailable is never a hard
failure — every function degrades to "always miss, caller recomputes",
matching how the rest of this app treats Redis as optional.
"""

import json
import logging
from typing import Any

logger = logging.getLogger("hirelens")

CACHE_PREFIX = "hirelens:cache:"


def cache_get(redis, key: str) -> Any | None:
    """Returns the cached value for `key`, or None on a miss / any error."""
    if not redis:
        return None
    try:
        raw = redis.get(CACHE_PREFIX + key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"cache_get({key}) failed, treating as a miss: {e}")
        return None


def cache_set(redis, key: str, value: Any, ttl_seconds: int) -> None:
    """Best-effort cache write. Never raises — a failed cache write should
    never break the request that computed the value."""
    if not redis:
        return
    try:
        redis.set(CACHE_PREFIX + key, json.dumps(value), ex=ttl_seconds)
    except Exception as e:
        logger.warning(f"cache_set({key}) failed (continuing without caching it): {e}")


def cache_delete(redis, key: str) -> None:
    """Best-effort cache invalidation."""
    if not redis:
        return
    try:
        redis.delete(CACHE_PREFIX + key)
    except Exception as e:
        logger.warning(f"cache_delete({key}) failed: {e}")
