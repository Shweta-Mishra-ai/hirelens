"""HireLens — Health Check (enhanced)"""

import logging
from fastapi import APIRouter, Depends
from app.core.config import settings
from app.core.dependencies import get_db, get_redis, get_current_user

logger = logging.getLogger("hirelens")
router = APIRouter()


def _snapshot(db, redis) -> dict:
    """
    The full picture, provider error text included.

    Deliberately a plain function rather than a route parameter: an argument
    on the public route would be a query parameter, and `?detail=true` would
    hand the error text to exactly the anonymous caller it is being kept
    from.
    """
    # Test DB connection
    db_status = "not_configured"
    db_error = None
    if db:
        try:
            # Simple query to verify connection
            db.table("reports").select("id").limit(1).execute()
            db_status = "ok"
        except Exception as e:
            # The provider's error text goes to the log and to the
            # authenticated diagnostics route, never into this response. This
            # is the one endpoint anyone can call without an account, and a
            # PostgREST or Postgres error routinely names the host, the
            # schema, or the reason a key was rejected — none of which a
            # passer-by needs in order to learn that the database is unwell.
            db_status = "error"
            db_error = str(e)
            logger.warning(f"Health check DB error: {e}")

    # Test Redis
    redis_status = "not_configured"
    redis_error = None
    if redis:
        try:
            redis.ping()
            redis_status = "ok"
        except Exception as e:
            redis_status = "error"
            redis_error = str(e)
            logger.warning(f"Health check Redis error: {e}")

    # LLM config
    llm_configured = bool(settings.GEMINI_API_KEY or settings.GROQ_API_KEY or settings.ANTHROPIC_API_KEY)

    overall = "ok" if llm_configured else "degraded"
    if db_status == "error" or redis_status == "error":
        overall = "degraded"

    payload = {
        "status": overall,
        "version": "1.0.0",
        "env": settings.APP_ENV,
        "services": {
            "database": db_status,
            "redis": redis_status,
            "gemini": "configured" if settings.GEMINI_API_KEY else "not_configured",
            "groq": "configured" if settings.GROQ_API_KEY else "not_configured",
            "anthropic": "configured" if settings.ANTHROPIC_API_KEY else "not_configured",
        },
        "llm_ready": llm_configured,
        # Google sign-in needs Supabase on BOTH sides: the browser starts the
        # OAuth flow with the public anon key, and this API exchanges the
        # resulting token via the service key. The frontend can only see its
        # own half, so it reads this flag for ours — otherwise the button
        # either disappears without explanation or appears and then fails at
        # the verification step.
        "google_auth_ready": bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY),
    }

    payload["errors"] = {
        key: value
        for key, value in (("database", db_error), ("redis", redis_error))
        if value
    }

    return payload


@router.get("/health", tags=["Health"])
async def health(db=Depends(get_db), redis=Depends(get_redis)):
    """
    Public health check, used by Render and by uptime monitors.

    Says whether each service is well, never why. A PostgREST or Postgres
    error routinely names the host, the schema, or the reason a key was
    rejected, and this is the one endpoint reachable without an account. The
    detail is in the log and in /health/diagnostics, which requires one.
    """
    payload = _snapshot(db, redis)
    payload.pop("errors", None)
    return payload


@router.get("/health/diagnostics", tags=["Health"])
async def diagnostics(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Detailed system diagnostics & load health metrics.
    Returns metrics on job queues, system limits, and process capacity.

    Requires authentication — this exposes internal process memory, active
    job counts, and rate-limit internals, which is reconnaissance-useful
    information and should never be reachable anonymously.
    """
    import os, time
    from app.api.v1.endpoints.analysis import _jobs
    from app.core.rate_limit import _mem_rate_limit

    h = _snapshot(db, redis)
    
    # Process memory estimate
    mem_mb = 0.0
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem_mb = round(process.memory_info().rss / (1024 * 1024), 2)
    except Exception:
        pass

    return {
        "health": h,
        "capacity": {
            "max_supported_users": 5000,
            "bulk_concurrency": settings.BULK_CONCURRENCY,
            "rate_limit_per_minute": settings.RATE_LIMIT_PER_MINUTE,
            "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
        },
        "metrics": {
            "active_in_memory_jobs": len(_jobs),
            "in_memory_rate_limit_keys": len(_mem_rate_limit),
            "process_memory_mb": mem_mb,
            "timestamp": time.time(),
        },
    }
