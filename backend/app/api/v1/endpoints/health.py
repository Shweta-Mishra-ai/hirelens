"""HireLens — Health Check (enhanced)"""

import logging
from fastapi import APIRouter, Depends
from app.core.config import settings
from app.core.dependencies import get_db, get_redis

logger = logging.getLogger("hirelens")
router = APIRouter()


@router.get("/health", tags=["Health"])
async def health(db=Depends(get_db), redis=Depends(get_redis)):
    """
    Health check endpoint.
    Returns status of all services.
    Used by Render for health checks.
    """
    # Test DB connection
    db_status = "not_configured"
    if db:
        try:
            # Simple query to verify connection
            db.table("reports").select("id").limit(1).execute()
            db_status = "ok"
        except Exception as e:
            db_status = f"error: {str(e)[:50]}"
            logger.warning(f"Health check DB error: {e}")

    # Test Redis
    redis_status = "not_configured"
    if redis:
        try:
            redis.ping()
            redis_status = "ok"
        except Exception as e:
            redis_status = f"error: {str(e)[:50]}"

    # LLM config
    llm_configured = bool(settings.GEMINI_API_KEY or settings.GROQ_API_KEY or settings.ANTHROPIC_API_KEY)

    overall = "ok" if llm_configured else "degraded"
    if "error" in db_status and db_status != "not_configured":
        overall = "degraded"

    return {
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
    }


@router.get("/health/diagnostics", tags=["Health"])
async def diagnostics(db=Depends(get_db), redis=Depends(get_redis)):
    """
    Detailed system diagnostics & load health metrics.
    Returns metrics on job queues, system limits, and process capacity.
    """
    import os, time
    from app.api.v1.endpoints.analysis import _jobs
    from app.core.rate_limit import _mem_rate_limit

    h = await health(db, redis)
    
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
