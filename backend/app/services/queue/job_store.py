"""
HireLens — Persistent Job/Report Store (Architecture Hardening)

Why this exists: `_jobs` was a plain in-memory Python dict shared across
analysis.py, bulk.py, match.py, verify.py, reports.py. It tracked every
analysis job's status AND served as the report-storage fallback when no
Supabase DB is configured. Being pure in-memory meant:

  1. A Render dyno restart (deploy, crash, idle-timeout wake) wiped every
     in-progress job and every report that hadn't made it to a real DB —
     a genuine reliability problem, not just a nice-to-have fix.
  2. It could never support more than one backend process/instance — a
     hard ceiling on horizontal scaling long before 10k users.

This class is a drop-in replacement with the EXACT SAME dict access
pattern (`d[k]`, `d.get(k)`, `k in d`, `del d[k]`, `.items()`) specifically
so none of the five call sites need risky logic rewrites — only two
in-place-mutation patterns (`d[k].update(...)` and `d[k]["x"] = y`, which
silently bypass persistence because they mutate the returned object
in-place rather than calling `__setitem__`) needed a one-line fix at their
3 call sites. Every write is mirrored to Redis (when configured) with a
TTL; every read checks the fast local in-memory cache first, then falls
through to Redis. No Redis configured → behaves exactly like the old
plain dict (same degrade-gracefully philosophy as the rest of the app).

Known limitation (documented, not silently swept under the rug): full-scan
iteration (`.items()`, used only by job cleanup and the in-memory report
listing fallback) only sees entries created in THIS process — after a
restart, individual lookups (`d[k]`) still correctly fall through to Redis,
but the "list everything" views only see what's been (re)created since. For
single-instance deployments (Render free tier today) this doesn't lose any
data — it's Redis, not gone — it just means the local listing cache needs
individual reads to repopulate. Fine for now; the moment this app runs on
more than one instance, per-user secondary indexes (e.g. a Redis SET of
each user's report IDs) would be the next step — noted for that point.
"""

import json
import time
import logging
from collections.abc import MutableMapping
from typing import Iterator

logger = logging.getLogger("hirelens")

STORE_TTL_SECONDS = 21_600  # 6 hours — matches BATCH_TTL_SECONDS elsewhere


class PersistentJobStore(MutableMapping):
    def __init__(self, get_redis_fn):
        """`get_redis_fn` is passed in (not imported directly) to avoid a
        circular import between this module and app.core.dependencies."""
        self._mem: dict[str, dict] = {}
        self._get_redis = get_redis_fn

    def _redis(self):
        try:
            return self._get_redis()
        except Exception as e:
            logger.warning(f"Job store could not obtain Redis client: {e}")
            return None

    def _key(self, k: str) -> str:
        return f"hirelens:store:{k}"

    def __getitem__(self, k: str) -> dict:
        if k in self._mem:
            return self._mem[k]
        redis = self._redis()
        if redis:
            try:
                raw = redis.get(self._key(k))
                if raw is not None:
                    val = json.loads(raw)
                    self._mem[k] = val
                    return val
            except Exception as e:
                logger.warning(f"Job store Redis read failed for '{k}': {e}")
        raise KeyError(k)

    def __setitem__(self, k: str, v: dict) -> None:
        self._mem[k] = v
        redis = self._redis()
        if redis:
            try:
                redis.set(self._key(k), json.dumps(v, default=str), ex=STORE_TTL_SECONDS)
            except Exception as e:
                logger.warning(f"Job store Redis write failed for '{k}': {e}")

    def __delitem__(self, k: str) -> None:
        self._mem.pop(k, None)
        redis = self._redis()
        if redis:
            try:
                redis.delete(self._key(k))
            except Exception as e:
                logger.warning(f"Job store Redis delete failed for '{k}': {e}")

    def __contains__(self, k: object) -> bool:
        if k in self._mem:
            return True
        redis = self._redis()
        if redis:
            try:
                return bool(redis.exists(self._key(k)))
            except Exception:
                return False
        return False

    def __iter__(self) -> Iterator[str]:
        # See module docstring: local-process keys only. Used for cleanup
        # and the in-memory report-listing fallback, both of which degrade
        # safely (not data loss) rather than silently misbehaving.
        return iter(list(self._mem))

    def __len__(self) -> int:
        return len(self._mem)

    def pop(self, k: str, default=None):
        try:
            v = self[k]
        except KeyError:
            return default
        del self[k]
        return v

    def cleanup_stale(self, max_age_seconds: int = 3600) -> int:
        """Removes local-memory entries older than max_age_seconds. Redis
        entries expire on their own via TTL — this only trims the process's
        local dict so it doesn't grow unbounded during a long-lived process."""
        cutoff = time.time() - max_age_seconds
        stale = [
            k for k, v in list(self._mem.items())
            if isinstance(v, dict) and v.get("created_at", time.time()) < cutoff
        ]
        for k in stale:
            self._mem.pop(k, None)
        return len(stale)
