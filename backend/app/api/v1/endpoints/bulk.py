"""
HireLens — Bulk CV Upload & Ranking API (Feature 1)

- Upload 50+ CVs in one request
- Each file becomes a job in the existing single-file job store (_jobs),
  so /api/v1/analysis/{job_id}/status and /api/v1/reports/{id} keep working
  exactly as before for bulk-uploaded files too.
- A Redis-backed (Upstash) batch registry groups job_ids under a batch_id
  and survives process restarts. Falls back to in-memory when Redis isn't
  configured, matching the rest of the app's degrade-gracefully pattern.
- Actual processing runs in-process via BackgroundTasks, throttled by an
  asyncio.Semaphore so we never fire 50 simultaneous Gemini/Groq calls at
  once (protects free-tier LLM rate limits and Render's free-tier RAM).
- Once jobs complete, candidates are auto-ranked by credibility score with
  a CSV export for recruiters.
"""

import io
import csv
import uuid
import asyncio
import logging
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.exceptions import NotFoundError, ForbiddenError, EmptyBatch, TooManyFiles, TooManyBatches, FileTooLarge
from app.api.v1.endpoints.analysis import _jobs, _run_analysis, _check_rate_limit, _cleanup_old_jobs, validate_upload
from app.services.queue import batch_store
from app.services.fraud.duplicate_detection import extract_fingerprint_text, find_duplicate_clusters

logger = logging.getLogger("hirelens")
router = APIRouter()

# Global cap on simultaneous AI analyses across ALL batches/users in this
# process — the real "queue" that keeps a 50-file upload from hammering
# the LLM provider all at once.
_bulk_semaphore = asyncio.Semaphore(settings.BULK_CONCURRENCY)


@router.post("/upload", status_code=202)
async def bulk_upload(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(..., description=f"Up to {settings.BULK_MAX_FILES} PDF/DOCX files"),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Upload many resumes at once → returns batch_id immediately.
    Poll GET /api/v1/bulk/{batch_id}/status for live progress + ranking.
    """
    if len(_jobs) > 200:
        _cleanup_old_jobs()
    batch_store.cleanup_old_batches()

    user_id = current_user["id"]

    if not files:
        raise EmptyBatch()
    if len(files) > settings.BULK_MAX_FILES:
        raise TooManyFiles(settings.BULK_MAX_FILES)

    active = batch_store.count_active_batches(redis, user_id)
    if active >= settings.BULK_MAX_CONCURRENT_BATCHES_PER_USER:
        raise TooManyBatches(settings.BULK_MAX_CONCURRENT_BATCHES_PER_USER)

    # One rate-limit tick per batch (not per file) — a batch is one action.
    _check_rate_limit(redis, user_id)

    # ── Read + validate every file up front ───────────────────────────────
    valid_items: list[dict] = []
    job_ids: list[str] = []
    total_bytes = 0

    for f in files:
        contents = await f.read()
        filename = (f.filename or "resume").strip()
        mime = (f.content_type or "").lower().strip()
        job_id = str(uuid.uuid4())
        job_ids.append(job_id)
        total_bytes += len(contents)

        try:
            effective_mime = validate_upload(contents, filename, mime)
        except Exception as e:
            message = getattr(e, "message", str(e))
            _jobs[job_id] = {
                "id": job_id, "user_id": user_id, "batch_id": None,
                "status": "failed", "stage": "failed", "progress": 0,
                "file_name": filename, "report_id": None,
                "error": f"Rejected: {message}",
                "created_at": __import__("time").time(),
            }
            continue

        _jobs[job_id] = {
            "id": job_id, "user_id": user_id, "batch_id": None,
            "status": "queued", "stage": "queued", "progress": 0,
            "file_name": filename, "report_id": None, "error": None,
            "created_at": __import__("time").time(),
        }
        valid_items.append({
            "job_id": job_id, "bytes": contents,
            "mime": effective_mime, "filename": filename,
        })

    total_mb = total_bytes / (1024 * 1024)
    if total_mb > settings.BULK_MAX_TOTAL_MB:
        # Roll back the jobs we just created — reject the whole batch.
        for jid in job_ids:
            _jobs.pop(jid, None)
        raise FileTooLarge(settings.BULK_MAX_TOTAL_MB)

    if not valid_items:
        raise EmptyBatch()

    batch_id = str(uuid.uuid4())
    for jid in job_ids:
        if jid in _jobs:
            _jobs[jid] = {**_jobs[jid], "batch_id": batch_id}

    batch_store.create_batch(redis, batch_id, user_id, job_ids, total=len(files))

    logger.info(
        f"Batch created | id={batch_id} user={user_id} files={len(files)} "
        f"valid={len(valid_items)} rejected={len(files) - len(valid_items)} size={total_mb:.1f}MB"
    )

    background_tasks.add_task(
        _run_batch, batch_id=batch_id, user_id=user_id,
        valid_items=valid_items, db=db, redis=redis,
    )

    return {
        "batch_id": batch_id,
        "total": len(files),
        "accepted": len(valid_items),
        "rejected": len(files) - len(valid_items),
        "message": f"Batch queued ({len(valid_items)} files). Poll /api/v1/bulk/{batch_id}/status every 2-3s.",
    }


async def _run_batch(batch_id: str, user_id: str, valid_items: list[dict], db, redis):
    """Runs each file's analysis, at most BULK_CONCURRENCY at a time."""

    async def run_one(item: dict):
        async with _bulk_semaphore:
            await _run_analysis(
                job_id=item["job_id"],
                user_id=user_id,
                file_bytes=item["bytes"],
                mime_type=item["mime"],
                filename=item["filename"],
                db=db,
            )

    try:
        await asyncio.gather(*(run_one(it) for it in valid_items), return_exceptions=True)
    finally:
        batch_store.release_batch(redis, user_id, batch_id)
        logger.info(f"[batch {batch_id}] all jobs finished")


def _get_report_summary(report_id: str, db) -> dict | None:
    """Lightweight report lookup for ranking — DB first, in-memory fallback."""
    if db:
        try:
            res = (
                db.table("reports")
                .select("id,file_name,candidate_name,overall_score,recommendation")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
            if res.data:
                return res.data
        except Exception as e:
            logger.warning(f"Ranking DB lookup failed for {report_id}: {e}")

    data = _jobs.get(f"report_{report_id}")
    if data:
        cred = data.get("credibility") or {}
        cand = data.get("candidate") or {}
        return {
            "id": report_id,
            "file_name": data.get("file_name"),
            "candidate_name": cand.get("name") or "Unknown",
            "overall_score": cred.get("overall", 0),
            "recommendation": cred.get("recommendation", "manual_review"),
        }
    return None


def _build_status_and_ranking(batch: dict, db) -> dict:
    job_ids = batch["job_ids"]
    jobs = []
    counts = {"queued": 0, "running": 0, "complete": 0, "failed": 0}
    ranking = []

    for jid in job_ids:
        job = _jobs.get(jid)
        if not job:
            jobs.append({
                "id": jid, "status": "failed", "stage": "failed", "progress": 0,
                "file_name": "unknown", "report_id": None,
                "error": "Job expired or not found.",
            })
            counts["failed"] += 1
            continue

        jobs.append({
            "id": job["id"], "status": job["status"], "stage": job["stage"],
            "progress": job["progress"], "file_name": job["file_name"],
            "report_id": job["report_id"], "error": job["error"],
        })
        counts[job["status"]] = counts.get(job["status"], 0) + 1

        if job["status"] == "complete" and job["report_id"]:
            summary = _get_report_summary(job["report_id"], db)
            if summary:
                ranking.append({
                    "report_id": job["report_id"],
                    "file_name": summary.get("file_name") or job["file_name"],
                    "candidate_name": summary.get("candidate_name") or "Unknown",
                    "overall_score": int(summary.get("overall_score") or 0),
                    "recommendation": summary.get("recommendation") or "manual_review",
                })

    ranking.sort(key=lambda r: r["overall_score"], reverse=True)
    for i, r in enumerate(ranking, start=1):
        r["rank"] = i

    total = batch["total"]
    done = counts["complete"] + counts["failed"]

    return {
        "batch_id": batch["id"],
        "total": total,
        "queued": counts["queued"],
        "running": counts["running"],
        "complete": counts["complete"],
        "failed": counts["failed"],
        "is_done": done >= total,
        "jobs": jobs,
        "ranking": ranking,
    }


@router.get("/{batch_id}/status")
async def bulk_status(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """Poll batch progress: per-file status + live ranking of completed candidates."""
    batch = batch_store.get_batch(redis, batch_id)
    if not batch:
        raise NotFoundError(f"Batch '{batch_id}' not found. It may have expired.")
    if batch["user_id"] != current_user["id"]:
        raise ForbiddenError()

    return _build_status_and_ranking(batch, db)


@router.get("/{batch_id}/export.csv")
async def bulk_export_csv(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """Export the ranked candidate list as a CSV for the recruiter."""
    batch = batch_store.get_batch(redis, batch_id)
    if not batch:
        raise NotFoundError(f"Batch '{batch_id}' not found. It may have expired.")
    if batch["user_id"] != current_user["id"]:
        raise ForbiddenError()

    result = _build_status_and_ranking(batch, db)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Rank", "Candidate Name", "File Name", "Score", "Recommendation", "Report ID"])
    for r in result["ranking"]:
        writer.writerow([
            r["rank"], r["candidate_name"], r["file_name"],
            r["overall_score"], r["recommendation"], r["report_id"],
        ])
    buf.seek(0)

    filename = f"hirelens_ranking_{batch_id[:8]}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _fetch_full_report(report_id: str, db) -> dict | None:
    """Fetches file_name/candidate/score + full report_data (needed to build
    a duplicate-detection fingerprint from experience bullets/projects)."""
    if db:
        try:
            res = (
                db.table("reports")
                .select("id,candidate_name,report_data")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
            if res.data:
                return res.data
        except Exception as e:
            logger.warning(f"Duplicate-detection DB lookup failed for {report_id}: {e}")

    data = _jobs.get(f"report_{report_id}")
    if data:
        cand = data.get("candidate") or {}
        return {"id": report_id, "candidate_name": cand.get("name") or "Unknown", "report_data": data}
    return None


@router.get("/{batch_id}/duplicates")
async def bulk_duplicate_check(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Cross-candidate duplicate/template detection — flags groups of
    candidates in this batch whose resume content (experience bullets,
    project descriptions) is suspiciously similar to each other. A single
    resume's own analysis can never catch this; it only shows up when
    candidates are compared against one another within a batch.

    High similarity is a signal to look closer, not proof of fraud —
    legitimate candidates in the same field sometimes describe similar
    work in similar words.
    """
    batch = batch_store.get_batch(redis, batch_id)
    if not batch:
        raise NotFoundError(f"Batch '{batch_id}' not found. It may have expired.")
    if batch["user_id"] != current_user["id"]:
        raise ForbiddenError()

    status = _build_status_and_ranking(batch, db)
    items = []
    for r in status["ranking"]:
        full = _fetch_full_report(r["report_id"], db)
        if not full:
            continue
        fingerprint = extract_fingerprint_text(full.get("report_data") or {})
        items.append({"id": r["report_id"], "name": full.get("candidate_name") or r["candidate_name"], "text": fingerprint})

    clusters = find_duplicate_clusters(items)

    return {
        "batch_id": batch_id,
        "candidates_compared": len(items),
        "clusters": clusters,
        "note": (
            "High similarity means these candidates' resume content is suspiciously "
            "alike — possibly the same template/writing service, or the same person "
            "applying multiple times. Always verify manually before acting on this."
        ),
    }
