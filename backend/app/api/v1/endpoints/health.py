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
