"""
HireLens — FastAPI Dependencies

Shared clients (Supabase, Redis) and the auth dependency.

Both clients are optional: when neither is configured the app runs on the
local SQLite store with in-memory rate limiting. The rule both follow is that
a client is only published to the rest of the app once it has been proven to
work, and a failed attempt is remembered for a short cooldown so a dead
dependency costs one connection timeout per cooldown rather than one per
request.
"""
import logging
import threading
import time
from fastapi import Depends, Header
from app.core.security import decode_token
from app.core.exceptions import AuthError
from app.core.config import settings

logger = logging.getLogger("hirelens")

# How long to wait before probing a dependency that just failed. Long enough
# that an outage does not cost every request a connection timeout, short
# enough that recovery is picked up without a redeploy.
_PROBE_COOLDOWN_SECONDS = 30.0


# ── Supabase DB — pooled singleton client ───────────────────────────────────
_supabase_client = None
_supabase_lock = threading.Lock()
_supabase_failed_at = 0.0


def get_db():
    """
    The shared Supabase client, or None when it is not configured or not
    reachable — callers fall back to the local store.

    The supabase-py v2 client is synchronous: call .execute() directly, never
    await it.
    """
    global _supabase_client, _supabase_failed_at

    if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY):
        return None
    if _supabase_client is not None:
        return _supabase_client

    with _supabase_lock:
        # Another thread may have built it while this one waited.
        if _supabase_client is not None:
            return _supabase_client
        if time.monotonic() - _supabase_failed_at < _PROBE_COOLDOWN_SECONDS:
            return None
        try:
            from supabase import create_client
            client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        except Exception as e:
            _supabase_failed_at = time.monotonic()
            logger.error(f"Supabase client creation failed: {e}")
            return None
        _supabase_client = client
        return client



# ── Redis — optional, graceful degradation ──────────────────────────────────
_redis_client = None
_redis_lock = threading.Lock()
_redis_failed_at = 0.0


def get_redis():
    """
    The shared Redis client, or None when Redis is not configured or not
    answering — callers fall back to their in-process equivalent.

    Two things matter here, and both are load-bearing:

    The client is published only after `ping()` proves it works. Assigning it
    before the probe means a single failed health check hands every later
    request a client that was never verified, and each of those requests then
    pays the full connect timeout before falling back.

    A failure is remembered for `_PROBE_COOLDOWN_SECONDS`. Without that, an
    unreachable Redis costs one connection timeout on every request that
    touches it — sign-in, upload, batch polling — which turns a degraded
    optional dependency into a slow app.
    """
    global _redis_client, _redis_failed_at

    if _redis_client is not None:
        return _redis_client
    if not settings.REDIS_URL:
        return None

    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        if time.monotonic() - _redis_failed_at < _PROBE_COOLDOWN_SECONDS:
            return None
        client = None
        try:
            import redis
            client = redis.from_url(
                settings.REDIS_URL,
                password=settings.REDIS_PASSWORD or None,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            client.ping()
        except Exception as e:
            _redis_failed_at = time.monotonic()
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            logger.warning(
                f"Redis unavailable, falling back to in-process state "
                f"(retrying in {_PROBE_COOLDOWN_SECONDS:.0f}s): {e}"
            )
            return None
        _redis_client = client
        logger.info("Redis connected")
        return client


def reset_clients() -> None:
    """Drop both cached clients and any cooldown, so the next call probes
    afresh. Used by tests to keep one case from leaking into the next."""
    global _supabase_client, _redis_client, _supabase_failed_at, _redis_failed_at
    with _supabase_lock:
        _supabase_client = None
        _supabase_failed_at = 0.0
    with _redis_lock:
        if _redis_client is not None:
            try:
                _redis_client.close()
            except Exception:
                pass
        _redis_client = None
        _redis_failed_at = 0.0


# ── Auth dependency ───────────────────────────────────────────────────────────
async def get_current_user(authorization: str = Header(default="")) -> dict:
    """
    Validates Bearer JWT token from Authorization header.
    Raises AuthError (401) if missing, invalid, or expired.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Authorization header missing or invalid. Format: 'Bearer <token>'")
    
    token = authorization[7:].strip()  # Remove "Bearer " prefix
    if not token:
        raise AuthError("Token is empty.")
    
    payload = decode_token(token)
    
    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise AuthError("Token missing user ID.")
    
    email = payload.get("email", "")
    return {"id": str(user_id), "email": email}


async def get_optional_user(authorization: str = Header(default="")) -> dict | None:
    """Returns user dict or None — for public endpoints."""
    try:
        return await get_current_user(authorization)
    except AuthError:
        return None
