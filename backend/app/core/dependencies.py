"""
HireLens — FastAPI Dependencies
Fixed: Supabase client properly initialized, no stale singletons,
Redis graceful degradation, auth header validation.
"""
import logging
from fastapi import Depends, Header
from app.core.security import decode_token
from app.core.exceptions import AuthError
from app.core.config import settings

logger = logging.getLogger("hirelens")


# ── Supabase DB — pooled singleton client (thread-safe) ─────────────────────
_supabase_client = None

def get_db():
    """
    Returns Supabase client or None.
    Supabase Python v2 client is synchronous — do NOT await its methods.
    Use .execute() directly (no await). Reuses a singleton instance for high-concurrency performance.
    """
    global _supabase_client
    if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY):
        logger.warning("Supabase not configured — DB unavailable")
        return None
    if _supabase_client is not None:
        return _supabase_client
    try:
        from supabase import create_client
        _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        return _supabase_client
    except Exception as e:
        logger.error(f"Supabase client creation failed: {e}")
        return None



# ── Redis — optional, graceful degradation ────────────────────────────────────
_redis_client = None

def get_redis():
    """Returns Redis client or None. Rate limiting disabled if unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.REDIS_URL:
        return None
    try:
        import redis
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        _redis_client.ping()
        logger.info("Redis connected")
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis unavailable — rate limiting disabled: {e}")
        return None


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
