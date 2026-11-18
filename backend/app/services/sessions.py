"""
Session revocation.

Session tokens are stateless and valid for seven days, so on their own they
cannot be withdrawn: a password reset used to leave every existing session —
a stolen one included — working until it expired.

A revocation records a moment for a user. Any token issued (`iat`) before it
is refused. Two things write one: a password reset, and "sign out
everywhere". Every authenticated request reads it, through a short in-process
cache, so the cost is at most one small query per user per CACHE_SECONDS.

Two deliberate choices:

* A failed lookup lets the request through. A database blip must not sign
  every user out at once; the token is still signed and unexpired.
* Comparison is in milliseconds (`iat_ms`), so a sign-in immediately after
  a revocation is accepted and a token from just before it is not. Tokens
  minted before `iat_ms` existed fall back to `iat` in seconds.
"""

import logging
import threading
import time
from datetime import datetime, timezone

from app.core import local_db

logger = logging.getLogger("hirelens")

CACHE_SECONDS = 60.0
_cache: dict[str, tuple[float, int]] = {}  # user_id -> (fetched_at, revoked_before_ms)
_lock = threading.Lock()


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _parse_ms(value) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return 0


def revoked_before(db, user_id: str) -> int:
    """Epoch milliseconds before which this user's tokens are refused; 0 for none."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(user_id)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]

    value = 0
    try:
        if db:
            res = (
                db.table("session_revocations")
                .select("revoked_before")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            value = _parse_ms(rows[0].get("revoked_before")) if rows else 0
        else:
            value = local_db.get_revoked_before(user_id)
    except Exception as e:
        logger.warning(f"Session revocation lookup failed for {user_id}; allowing: {e}")
        return 0

    with _lock:
        _cache[user_id] = (now, value)
        if len(_cache) > 10_000:
            cutoff = now - CACHE_SECONDS
            for key in [k for k, (t, _) in _cache.items() if t < cutoff]:
                _cache.pop(key, None)
    return value


def is_revoked(db, user_id: str, payload: dict) -> bool:
    cutoff = revoked_before(db, user_id)
    if not cutoff:
        return False
    try:
        if payload.get("iat_ms") is not None:
            issued = int(payload["iat_ms"])
        else:
            issued = int(payload.get("iat")) * 1000
    except (TypeError, ValueError):
        # Tokens from before `iat` existed predate any revocation.
        issued = 0
    return issued < cutoff


def revoke_all(db, user_id: str) -> None:
    """
    End every session this user has open, as of now. Raises if the
    revocation could not be stored anywhere — "signed out everywhere" must
    not be reported when nothing was.
    """
    from app.core.exceptions import StorageWriteFailed

    now_ms = _now_ms()
    stored = False
    if db:
        try:
            db.table("session_revocations").upsert(
                {
                    "user_id": user_id,
                    "revoked_before": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(),
                },
                on_conflict="user_id",
            ).execute()
            stored = True
        except Exception as e:
            logger.error(f"Session revocation not stored in Supabase for {user_id}: {e}")
    if not stored:
        stored = local_db.set_revoked_before(user_id, now_ms)
    if not stored:
        raise StorageWriteFailed("Your other sessions could not be signed out. Please try again.")
    with _lock:
        _cache[user_id] = (time.monotonic(), now_ms)


def clear_cache() -> None:
    with _lock:
        _cache.clear()
