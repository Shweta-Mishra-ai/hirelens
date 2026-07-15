"""
HireLens — Bulk Upload Batch Store
Backs batch metadata (list of job_ids belonging to a batch, owner, counters)
with Upstash Redis when configured, falling back to an in-memory dict when
Redis is unavailable — same graceful-degradation pattern used elsewhere
in this codebase (see app/core/dependencies.py get_redis()).

Per-file job progress continues to live in the existing in-memory `_jobs`
dict in analysis.py so that /api/v1/analysis/{job_id}/status keeps working
unchanged for both single and bulk uploads. This store only tracks the
*grouping* of job_ids into a batch plus lightweight owner/limit bookkeeping,
which is exactly what needs to survive a Render dyno restart mid-batch.
"""

import json
import time
import logging
from app.core.config import settings

logger = logging.getLogger("hirelens")

_mem_batches: dict[str, dict] = {}
_mem_active_batches_by_user: dict[str, set[str]] = {}


def _key(batch_id: str) -> str:
    return f"hirelens:batch:{batch_id}"


def _active_key(user_id: str) -> str:
    return f"hirelens:active_batches:{user_id}"


def create_batch(redis, batch_id: str, user_id: str, job_ids: list[str], total: int) -> dict:
    data = {
        "id": batch_id,
        "user_id": user_id,
        "job_ids": job_ids,
        "total": total,
        "created_at": time.time(),
    }
    _mem_batches[batch_id] = data
    _mem_active_batches_by_user.setdefault(user_id, set()).add(batch_id)

    if redis:
        try:
            redis.set(_key(batch_id), json.dumps(data), ex=settings.BATCH_TTL_SECONDS)
            redis.sadd(_active_key(user_id), batch_id)
            redis.expire(_active_key(user_id), settings.BATCH_TTL_SECONDS)
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
    """Best-effort count of batches a user currently has running (for the
    per-user concurrent-batch limit). Falls back to in-memory tracking."""
    if redis:
        try:
            return int(redis.scard(_active_key(user_id)) or 0)
        except Exception as e:
            logger.warning(f"Redis active-batch count failed: {e}")
    return len(_mem_active_batches_by_user.get(user_id, set()))


def release_batch(redis, user_id: str, batch_id: str) -> None:
    """Call once every job in a batch reaches a terminal state, so the
    per-user concurrent-batch slot frees up."""
    _mem_active_batches_by_user.get(user_id, set()).discard(batch_id)
    if redis:
        try:
            redis.srem(_active_key(user_id), batch_id)
        except Exception as e:
            logger.warning(f"Redis batch release failed: {e}")


def cleanup_old_batches() -> None:
    """Remove stale in-memory batches past TTL (Redis entries expire on their own)."""
    cutoff = time.time() - settings.BATCH_TTL_SECONDS
    stale = [b for b, d in _mem_batches.items() if d.get("created_at", 0) < cutoff]
    for b in stale:
        _mem_batches.pop(b, None)
    if stale:
        logger.info(f"Cleaned up {len(stale)} stale batches")
