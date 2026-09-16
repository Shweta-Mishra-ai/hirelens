"""
HireLens — Bulk Upload Batch Store

Tracks the grouping of job_ids into a batch, its owner, and which of a user's
concurrent-batch slots are in use. Backed by Redis when configured, with an
in-process fallback — the same graceful-degradation pattern used elsewhere
(see app/core/dependencies.py get_redis()).

Per-file job progress stays in the in-memory `_jobs` dict in analysis.py, so
/api/v1/analysis/{job_id}/status works unchanged for single and bulk uploads
alike. This store only holds what needs to survive a restart mid-batch.

Concurrent-batch slots are held on a **lease**, not until an explicit release.
A batch normally releases its slot when its runner finishes, but a runner that
dies with the process — a deploy, or a free-tier container going to sleep —
never gets to. Anything holding a slot for longer than BATCH_LEASE_SECONDS is
treated as abandoned and reclaimed, so an interrupted batch costs a user a slot
for the length of the lease rather than until the key expires hours later.
"""

import json
import time
import logging
from app.core.config import settings

logger = logging.getLogger("hirelens")

_mem_batches: dict[str, dict] = {}
# user_id -> {batch_id: started_at}. The timestamp is what makes a slot
# reclaimable; a bare set cannot say how long it has been held.
_mem_leases: dict[str, dict[str, float]] = {}


def _key(batch_id: str) -> str:
    return f"hirelens:batch:{batch_id}"


def _lease_key(user_id: str) -> str:
    # Deliberately not the old `hirelens:active_batches:*` name: that key is a
    # SET in any already-running deployment, and issuing a sorted-set command
    # against it would fail with WRONGTYPE until it expired.
    return f"hirelens:batch_leases:{user_id}"


def _prune_mem_leases(user_id: str, now: float) -> dict[str, float]:
    leases = _mem_leases.get(user_id)
    if not leases:
        _mem_leases.pop(user_id, None)
        return {}
    cutoff = now - settings.BATCH_LEASE_SECONDS
    live = {b: t for b, t in leases.items() if t > cutoff}
    if live:
        _mem_leases[user_id] = live
    else:
        _mem_leases.pop(user_id, None)
    return live


def create_batch(redis, batch_id: str, user_id: str, job_ids: list[str], total: int) -> dict:
    now = time.time()
    data = {
        "id": batch_id,
        "user_id": user_id,
        "job_ids": job_ids,
        "total": total,
        "created_at": now,
    }
    _mem_batches[batch_id] = data
    _mem_leases.setdefault(user_id, {})[batch_id] = now

    if redis:
        try:
            redis.set(_key(batch_id), json.dumps(data), ex=settings.BATCH_TTL_SECONDS)
            redis.zadd(_lease_key(user_id), {batch_id: now})
            redis.expire(_lease_key(user_id), settings.BATCH_LEASE_SECONDS)
        except Exception as e:
            logger.warning(f"Redis batch persist failed (using memory only): {e}")

    return data


def get_batch(redis, batch_id: str) -> dict | None:
    if batch_id in _mem_batches:
        return _mem_batches[batch_id]
    if redis:
        try:
            raw = redis.get(_key(batch_id))
            if raw:
                data = json.loads(raw)
                _mem_batches[batch_id] = data
                return data
        except Exception as e:
            logger.warning(f"Redis batch fetch failed: {e}")
    return None


def count_active_batches(redis, user_id: str) -> int:
    """
    How many concurrent-batch slots this user currently holds.

    Expired leases are dropped first, so a batch whose runner died with the
    process stops counting against the user once its lease runs out.

    The answer is the larger of what Redis and memory report. They can
    disagree — a write to one of them may have failed — and under-counting
    would quietly disable the per-user limit, which is the thing protecting
    a free-tier container from a user queueing fifty analyses at a time.
    """
    now = time.time()
    counts = [len(_prune_mem_leases(user_id, now))]

    if redis:
        try:
            key = _lease_key(user_id)
            redis.zremrangebyscore(key, 0, now - settings.BATCH_LEASE_SECONDS)
            counts.append(int(redis.zcard(key) or 0))
        except Exception as e:
            logger.warning(f"Redis active-batch count failed (using memory): {e}")

    return max(counts)


def release_batch(redis, user_id: str, batch_id: str) -> None:
    """Called once every job in a batch reaches a terminal state, so the
    per-user concurrent-batch slot frees up without waiting for its lease."""
    leases = _mem_leases.get(user_id)
    if leases is not None:
        leases.pop(batch_id, None)
        if not leases:
            _mem_leases.pop(user_id, None)

    if redis:
        try:
            redis.zrem(_lease_key(user_id), batch_id)
        except Exception as e:
            logger.warning(f"Redis batch release failed: {e}")


def cleanup_old_batches() -> None:
    """Drop in-memory batch records and leases past their lifetime. Redis
    entries expire on their own."""
    now = time.time()
    cutoff = now - settings.BATCH_TTL_SECONDS
    stale = [b for b, d in _mem_batches.items() if d.get("created_at", 0) < cutoff]
    for b in stale:
        _mem_batches.pop(b, None)

    # Leases expire far sooner than batch records, and an untouched user entry
    # would otherwise sit in the dict for the life of the process.
    for user_id in list(_mem_leases):
        _prune_mem_leases(user_id, now)

    if stale:
        logger.info(f"Cleaned up {len(stale)} stale batches")
