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
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, File, UploadFile, BackgroundTasks

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.exceptions import (
    FileTooLarge,
    UnsupportedFileType,
    NotFoundError,
    ForbiddenError,
    AnalysisUnavailable,
)
from app.services.parser.document_parser import extract_text, check_magic_bytes
from app.services.parser.resume_heuristic import looks_like_resume
from app.services.ai.engine import engine
from app.services.queue.job_store import PersistentJobStore
from app.core import local_db

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
    """
    Rate limiting for expensive upload endpoints (analysis, bulk, match, ats).

    This used to `return` immediately whenever redis was falsy — meaning
    with REDIS_URL unset (the shipped default), these endpoints had NO
    rate limit at all. core.rate_limit.check_rate_limit() already has a
    proper in-memory fallback (a module-level dict, cleaned up
    opportunistically) for exactly this situation; this function now
    delegates to it instead of re-implementing a weaker version. Kept as
    a thin wrapper so existing callers (analysis.py, bulk.py, match.py,
    ats.py) don't need to change their call sites.
    """
    from app.core.rate_limit import check_rate_limit
    check_rate_limit(redis, user_id, settings.RATE_LIMIT_PER_MINUTE, window_seconds=60)


def require_analysis_available() -> None:
    """
    Reject an upload up front when there is no AI provider to run it.

    Accepting a file we already know cannot be processed costs the user the
    upload, a ~15-second wait and a confusing failure. The condition is
    static — it depends only on configuration — so there is no reason to
    discover it asynchronously in a background task.
    """
    if not any((settings.GEMINI_API_KEY, settings.GROQ_API_KEY, settings.ANTHROPIC_API_KEY)):
        logger.error("Upload rejected: no LLM provider configured (set GEMINI_API_KEY)")
        raise AnalysisUnavailable()


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

    # Refuse before reading the file if there is no provider to analyse it.
    require_analysis_available()

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


def _recover_finished_job(job_id: str, user_id: str, db) -> dict | None:
    """
    Find the report an analysis job produced, when the job itself is gone.

    Progress lives in `_jobs`, a process-local dict. The report does not — it
    is written to Supabase (or the local store) the moment analysis finishes.
    So a restart between those two facts leaves a recruiter polling for a job
    this process has never heard of, while their finished report sits on the
    dashboard.

    On a free tier that is not an edge case: the container is replaced on
    every deploy and every wake from sleep, and an analysis takes up to two
    minutes. The endpoint used to answer 404 and the UI told them to upload
    again — a second LLM call, a second charge, and a duplicate report for a
    CV that had already been analysed.
    """
    if db:
        try:
            res = (
                db.table("reports")
                .select("id,file_name")
                .eq("job_id", job_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if rows:
                return {"id": rows[0].get("id"), "file_name": rows[0].get("file_name")}
        except Exception as e:
            logger.warning(f"Could not look up the report for job {job_id}: {e}")

    return local_db.find_report_by_job(job_id, user_id)


@router.get("/{job_id}/status")
async def get_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Poll analysis job status. Returns progress, stage, and report_id when complete."""
    job = _jobs.get(job_id)
    if not job:
        recovered = _recover_finished_job(job_id, current_user["id"], db)
        if recovered:
            logger.info(
                f"Job {job_id} was lost with the process, but its report "
                f"{recovered['id']} survived — reporting it as complete"
            )
            return {
                "id": job_id,
                "status": "complete",
                "stage": "complete",
                "progress": 100,
                "file_name": recovered.get("file_name") or "",
                "report_id": recovered["id"],
                "error": None,
            }
        raise NotFoundError(
            f"Job '{job_id}' not found. It may have expired — jobs are kept for an hour, "
            "and a finished report would be on your dashboard."
        )
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


def _stamp_report_metadata(result: dict, *, user_id: str, filename: str, report_id: str) -> dict:
    """
    Attach the ownership and display metadata that the Supabase `reports` row
    would otherwise carry, so the in-memory path is not a second-class
    citizen.

    Two fields here were previously missing or misnamed, and both were
    visible to users:

    * `file_name` — the writer stamped `_owner_file_name`, but every reader
      (reports.py's list, CSV export and search) looked for `file_name`. The
      dashboard therefore showed a blank filename for every report whenever
      the DB path wasn't taken, and searching by filename never matched.
    * `created_at` — nothing set it at all. The list endpoint emitted `""`,
      and the dashboard rendered that as "NaNd ago".

    `_owner_file_name` is still written for backwards compatibility with
    report blobs persisted by an earlier version.
    """
    now = datetime.now(timezone.utc).isoformat()
    result["id"] = report_id
    result["_owner_user_id"] = user_id
    result["_owner_file_name"] = filename
    result["file_name"] = filename
    result["created_at"] = now
    return result

def _persist_report_locally(
    result: dict, *, report_id: str, user_id: str, filename: str, job_id: str | None = None
) -> None:
    """
    Write the report to the local SQLite store.

    This is what makes a report survive a restart. Before it existed, a
    deployment without Supabase kept reports only in `_jobs`, a process-local
    dict — so every Render free-tier sleep, redeploy or crash silently
    discarded everything the recruiter had analysed.

    Failure here is logged and swallowed: the in-memory copy is still good
    for this process, and a storage problem should not turn a completed
    analysis into a failed job.
    """
    credibility = result.get("credibility") or {}
    candidate = result.get("candidate") or {}
    saved = local_db.save_report(
        report_id=report_id,
        user_id=user_id,
        file_name=filename,
        candidate_name=candidate.get("name") or "Unknown",
        overall_score=int(credibility.get("overall") or 0),
        recommendation=credibility.get("recommendation") or "manual_review",
        report_data=result,
        created_at=result.get("created_at"),
        job_id=job_id,
    )
    if not saved:
        logger.warning(
            f"Report {report_id} could not be persisted locally — it will be lost "
            f"when this process restarts."
        )


def _parse_failure_message(filename: str, error: Exception) -> str:
    """
    Turn a parser exception into something a recruiter can act on.

    The raw exception text was previously passed straight through, which
    surfaced messages like "No /Root object! - Is this really a PDF?" —
    accurate, but it tells the user nothing about what to do next.
    """
    detail = str(error).strip()
    lowered = detail.lower()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if "scan" in lowered or "text-selectable" in lowered or "no text" in lowered:
        return (
            "This file has no selectable text — it looks like a scan or a set of "
            "images. Ask the candidate for the original PDF or DOCX, or run it "
            "through OCR first."
        )
    if "password" in lowered or "encrypt" in lowered:
        return (
            "This file is password-protected, so its text could not be read. "
            "Ask the candidate for an unprotected copy."
        )
    if "root object" in lowered or "really a pdf" in lowered or "corrupt" in lowered:
        return (
            f"This file could not be opened as a {ext.upper() or 'document'}. It may be "
            "corrupted, or saved with the wrong extension. Try re-exporting it."
        )
    return (
        "This file could not be read. Make sure it is a text-based PDF or DOCX "
        "and try again."
    )


def _analysis_failure_message(error: Exception) -> str:
    """
    Map an engine failure to recruiter-facing copy.

    Never echo the provider's raw error: it can name internal configuration
    ("set GEMINI_API_KEY in your .env file"), which is advice for the
    operator, not the person waiting on a report.
    """
    detail = str(error).lower()

    if "rate limit" in detail or "429" in detail:
        return (
            "The AI provider is rate-limiting requests right now. Wait a minute "
            "and try again — nothing was lost."
        )
    if "timed out" in detail or "timeout" in detail:
        return (
            "Analysis took longer than expected and was stopped. This usually "
            "means an unusually long resume — try again, or split it up."
        )
    if "no llm api key" in detail or "no provider" in detail:
        return (
            "Resume analysis is not configured on this server. Contact your "
            "administrator."
        )
    if "blocked" in detail or "safety" in detail:
        return (
            "The AI provider declined to process this document. If it contains "
            "unusual content, review the original file directly."
        )
    return (
        "Analysis could not be completed. This is usually temporary — please "
        "try again in a moment."
    )


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
            upd(status="failed", stage="failed", error=_parse_failure_message(filename, e))
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
            upd(status="failed", stage="failed", error=_analysis_failure_message(e))
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
                # Store in memory as fallback so report is still accessible.
                # user_id and file_name are stamped onto the blob itself here —
                # without this, the in-memory read/list/delete paths in
                # reports.py have no reliable way to check ownership, which
                # was a real access-control gap (any authenticated user could
                # read/list/delete any in-memory report). See reports.py's
                # _mem_reports_for_user() and get_report() for the read side.
                _stamp_report_metadata(result, user_id=user_id, filename=filename, report_id=report_id)
                _persist_report_locally(
                result, report_id=report_id, user_id=user_id, filename=filename, job_id=job_id
            )
                _jobs[f"report_{report_id}"] = result
        else:
            # No DB configured — persist to the local store, and keep a copy
            # in memory as a read-through cache for this process.
            logger.info(f"[{job_id}] No Supabase — storing report {report_id} locally")
            _stamp_report_metadata(result, user_id=user_id, filename=filename, report_id=report_id)
            _persist_report_locally(
                result, report_id=report_id, user_id=user_id, filename=filename, job_id=job_id
            )
            _jobs[f"report_{report_id}"] = result

        upd(status="complete", stage="complete", progress=100, report_id=report_id)
        logger.info(
            f"[{job_id}] Complete | report={report_id} "
            f"score={result.get('credibility', {}).get('overall')} "
            f"rec={result.get('credibility', {}).get('recommendation')}"
        )

    except Exception as e:
        # Catch-all — should never reach here
        logger.error(f"[{job_id}] Unexpected error in background task: {e}", exc_info=True)
        upd(status="failed", stage="failed", error="Unexpected server error. Please try again.")
