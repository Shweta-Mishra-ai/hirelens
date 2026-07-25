"""
HireLens — Analysis API
Fixed:
- Supabase .execute() is SYNC — no await
- MIME type detection improved (browsers send wrong types)
- Job cleanup after 1 hour to prevent memory leak
- Background task error isolation
- Rate limiting with Redis (sync client)
"""

import uuid
import time
import logging
from typing import Annotated
from fastapi import APIRouter, Depends, File, UploadFile, BackgroundTasks

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.exceptions import FileTooLarge, UnsupportedFileType, NotFoundError, ForbiddenError
from app.services.parser.document_parser import extract_text, check_magic_bytes
from app.services.parser.resume_heuristic import looks_like_resume
from app.services.ai.engine import engine
from app.services.queue.job_store import PersistentJobStore

logger = logging.getLogger("hirelens")
router = APIRouter()

# Job/report store — Redis-backed when REDIS_URL is configured (survives
# process restarts), transparent in-memory-only fallback otherwise.
# Key: job_id -> job status dict, OR "report_{id}" -> full report dict.
_jobs = PersistentJobStore(get_redis_fn=get_redis)

ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # Some browsers/OS send these variants
    "application/msword",
    "application/x-pdf",
    "binary/octet-stream",
    "application/octet-stream",
}

ALLOWED_EXT = {"pdf", "docx"}


def _cleanup_old_jobs():
    """Trims local-memory entries older than 1 hour. Redis-backed entries
    (when configured) expire on their own via TTL — this only prevents the
    process's local dict from growing unbounded over a long uptime."""
    removed = _jobs.cleanup_stale(max_age_seconds=3600)
    if removed:
        logger.info(f"Cleaned up {removed} stale jobs")


def _check_rate_limit(redis, user_id: str) -> None:
    """Simple Redis rate limiting. Skips if Redis unavailable."""
    if not redis:
        return
    try:
        key = f"rl:{user_id}:{int(time.time()) // 60}"
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, 60)
        if count > settings.RATE_LIMIT_PER_MINUTE:
            from app.core.exceptions import RateLimitExceeded
            raise RateLimitExceeded(retry_after=60)
    except Exception as e:
        # Don't block upload if Redis has issues
        if "RateLimitExceeded" in type(e).__name__:
            raise
        logger.warning(f"Rate limit check failed (skipping): {e}")


def validate_upload(contents: bytes, filename: str, mime: str) -> str:
    """
    Shared validation for a single resume file (used by both the single-file
    /upload endpoint and the /bulk/upload endpoint). Returns the normalized
    effective MIME type, or raises UnsupportedFileType / FileTooLarge.
    """
    if not contents:
        raise UnsupportedFileType("empty file")

    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise FileTooLarge(settings.MAX_FILE_SIZE_MB)

    filename = (filename or "").strip()
    mime = (mime or "").lower().strip()

    # Detect file type — prefer extension (more reliable than browser MIME)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ALLOWED_EXT and mime not in ALLOWED_MIME:
        raise UnsupportedFileType(f"{mime or ext or 'unknown'}")

    # Normalize mime type for parser
    if ext == "pdf" or mime == "application/pdf":
        effective_mime = "application/pdf"
        fmt = "pdf"
    elif ext == "docx" or "wordprocessingml" in mime:
        effective_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        fmt = "docx"
    elif ext == "pdf":
        effective_mime = "application/pdf"
        fmt = "pdf"
    else:
        effective_mime = "application/pdf"  # default, parser will validate
        fmt = "pdf"

    # Validate header magic bytes
    check_magic_bytes(contents, fmt)

    return effective_mime


@router.post("/upload")
async def upload_resume(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF or DOCX, max 10MB")],
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Upload resume → returns job_id immediately (202 Accepted).
    Background task runs AI analysis (~10-30s).
    Poll /analysis/{job_id}/status for progress updates.
    """
    # Cleanup old jobs periodically
    if len(_jobs) > 100:
        _cleanup_old_jobs()

    # Rate limit check
    _check_rate_limit(redis, current_user["id"])

    # Read file
    contents = await file.read()
    filename = (file.filename or "").strip()
    mime = (file.content_type or "").lower().strip()

    effective_mime = validate_upload(contents, filename, mime)

    job_id = str(uuid.uuid4())
    user_id = current_user["id"]
    size_mb = len(contents) / (1024 * 1024)

    _jobs[job_id] = {
        "id": job_id,
        "user_id": user_id,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "file_name": filename or "resume",
        "report_id": None,
        "error": None,
        "created_at": time.time(),
    }

    logger.info(f"Job created | id={job_id} user={user_id} file={filename} size={size_mb:.1f}MB mime={effective_mime}")

    background_tasks.add_task(
        _run_analysis,
        job_id=job_id,
        user_id=user_id,
        file_bytes=contents,
        mime_type=effective_mime,
        filename=filename or "resume",
        db=db,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "message": f"Analysis queued. Poll /api/v1/analysis/{job_id}/status every 2s.",
    }


@router.get("/{job_id}/status")
async def get_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Poll analysis job status. Returns progress, stage, and report_id when complete."""
    job = _jobs.get(job_id)
    if not job:
        raise NotFoundError(f"Job '{job_id}' not found. It may have expired (jobs kept 1 hour).")
    if job["user_id"] != current_user["id"]:
        raise ForbiddenError()

    # Return without internal fields
    return {
        "id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "file_name": job["file_name"],
        "report_id": job["report_id"],
        "error": job["error"],
    }


# ── Background Analysis Task ──────────────────────────────────────────────────

async def _run_analysis(
    job_id: str,
    user_id: str,
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    db,
    post_process=None,
):
    """
    Runs in background. Updates _jobs[job_id] with progress.
    All exceptions are caught — never crashes the server.

    post_process: optional async callable (result: dict) -> dict, run after
    AI analysis but before storage. Lets other features (e.g. JD matching)
    enrich the report without duplicating the parse/analyze/store pipeline.
    """

    def upd(**kwargs):
        if job_id in _jobs:
            _jobs[job_id] = {**_jobs[job_id], **kwargs}

    async def on_progress(stage: str, pct: int):
        upd(stage=stage, progress=pct, status="running")

    try:
        upd(status="running", stage="parsing", progress=5)

        # ── Step 1: Parse document ────────────────────────────────────────────
        try:
            raw_text = extract_text(file_bytes, mime_type, filename)
        except Exception as e:
            logger.error(f"[{job_id}] Parse failed: {e}")
            upd(status="failed", stage="failed", error=f"Could not read file: {str(e)}")
            return

        logger.info(f"[{job_id}] Parsed {len(raw_text)} chars from {filename}")
        upd(stage="extracting", progress=15)

        # ── Step 1b: Reject obviously-non-resume documents ─────────────────────
        is_resume, rejection_reason = looks_like_resume(raw_text)
        if not is_resume:
            logger.warning(f"[{job_id}] Rejected as non-resume: {filename}")
            upd(status="failed", stage="failed", error=rejection_reason)
            return

        # ── Step 2: AI analysis ───────────────────────────────────────────────
        try:
            result = await engine.run(raw_text=raw_text, on_progress=on_progress)
        except Exception as e:
            logger.error(f"[{job_id}] AI analysis failed: {e}", exc_info=True)
            upd(status="failed", stage="failed", error=f"AI analysis failed: {str(e)}")
            return

        # ── Step 2b: Optional enrichment (e.g. JD match) ───────────────────────
        if post_process is not None:
            try:
                upd(stage="matching", progress=90)
                result = await post_process(result)
            except Exception as e:
                logger.warning(f"[{job_id}] post_process failed (continuing without it): {e}")

        # ── Step 3: Store in DB ───────────────────────────────────────────────
        report_id = str(uuid.uuid4())

        if db:
            try:
                # Supabase Python v2 — synchronous .execute(), NO await
                db.table("reports").insert({
                    "id": report_id,
                    "user_id": user_id,
                    "job_id": job_id,
                    "file_name": filename,
                    "candidate_name": (result.get("candidate") or {}).get("name") or "Unknown",
                    "overall_score": int((result.get("credibility") or {}).get("overall") or 0),
                    "recommendation": (result.get("credibility") or {}).get("recommendation") or "manual_review",
                    "report_data": result,
                }).execute()
                logger.info(f"[{job_id}] Stored report {report_id} in Supabase")
            except Exception as e:
                logger.warning(f"[{job_id}] DB store failed — using in-memory fallback: {e}")
                # Store in memory as fallback so report is still accessible
                _jobs[f"report_{report_id}"] = result
        else:
            # No DB configured — store in memory
            logger.info(f"[{job_id}] No DB — storing report {report_id} in memory")
            _jobs[f"report_{report_id}"] = result

        upd(status="complete", stage="complete", progress=100, report_id=report_id)
        logger.info(
            f"[{job_id}] ✓ Complete | report={report_id} "
            f"score={result.get('credibility', {}).get('overall')} "
            f"rec={result.get('credibility', {}).get('recommendation')}"
        )

    except Exception as e:
        # Catch-all — should never reach here
        logger.error(f"[{job_id}] Unexpected error in background task: {e}", exc_info=True)
        upd(status="failed", stage="failed", error="Unexpected server error. Please try again.")
