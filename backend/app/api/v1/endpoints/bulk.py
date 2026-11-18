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
import time
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File, Request
from pydantic import BaseModel, Field
from typing import Literal
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.services import billing, directory, report_lookup
from app.core.csv_safety import safe_row
from app.core.shapes import as_dict, as_str, as_score
from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.rate_limit import check_rate_limit
from app.core.exceptions import NotFoundError, ForbiddenError, EmptyBatch, TooManyFiles, TooManyBatches, FileTooLarge
from app.api.v1.endpoints.analysis import _jobs, _run_analysis, _check_rate_limit, _cleanup_old_jobs, validate_upload, require_analysis_available
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
    request: Request,
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
    require_analysis_available()
    _check_rate_limit(redis, user_id)
    # Every file in the batch must fit in this month's quota.
    await run_in_threadpool(billing.ensure_quota, db, user_id, len(files), _jobs)

    # ── Reject an oversized batch before reading anything ─────────────────
    # Content-Length is advisory (a client can lie, and it includes multipart
    # framing overhead), so it is a cheap early-out, not the real guard. The
    # running total inside the read loop below is what actually enforces the
    # cap.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit():
        declared_mb = int(declared) / (1024 * 1024)
        if declared_mb > settings.BULK_MAX_TOTAL_MB * 1.1:  # allow for framing
            logger.warning(
                f"Batch rejected on Content-Length | user={user_id} declared={declared_mb:.0f}MB"
            )
            raise FileTooLarge(settings.BULK_MAX_TOTAL_MB)

    # ── Read + validate every file up front ───────────────────────────────
    #
    # The cumulative size is checked as each file is read, and the loop stops
    # the moment the cap is passed. The previous version read every file
    # fully into memory and only then compared the total against
    # BULK_MAX_TOTAL_MB — so 50 files x 10MB reached ~500MB resident on a
    # 512MB instance before the 150MB limit was ever evaluated, and the
    # process was OOM-killed before it could reject anything.
    max_total_bytes = settings.BULK_MAX_TOTAL_MB * 1024 * 1024
    valid_items: list[dict] = []
    job_ids: list[str] = []
    total_bytes = 0

    for f in files:
        contents = await f.read()
        filename = (f.filename or "resume").strip()
        mime = (f.content_type or "").lower().strip()
        total_bytes += len(contents)

        if total_bytes > max_total_bytes:
            # Drop everything already buffered before raising, so the bytes
            # are reclaimable while the error response is being built.
            for item in valid_items:
                item["bytes"] = b""
            valid_items.clear()
            del contents
            for jid in job_ids:
                _jobs.pop(jid, None)
            logger.warning(
                f"Batch rejected mid-read | user={user_id} "
                f"at={total_bytes / (1024 * 1024):.0f}MB cap={settings.BULK_MAX_TOTAL_MB}MB"
            )
            raise FileTooLarge(settings.BULK_MAX_TOTAL_MB)

        job_id = str(uuid.uuid4())
        job_ids.append(job_id)

        try:
            effective_mime = validate_upload(contents, filename, mime)
        except Exception as e:
            message = getattr(e, "message", str(e))
            _jobs[job_id] = {
                "id": job_id, "user_id": user_id, "batch_id": None,
                "status": "failed", "stage": "failed", "progress": 0,
                "file_name": filename, "report_id": None,
                "error": f"Rejected: {message}",
                "created_at": time.time(),
            }
            continue

        _jobs[job_id] = {
            "id": job_id, "user_id": user_id, "batch_id": None,
            "status": "queued", "stage": "queued", "progress": 0,
            "file_name": filename, "report_id": None, "error": None,
            "created_at": time.time(),
        }
        valid_items.append({
            "job_id": job_id, "bytes": contents,
            "mime": effective_mime, "filename": filename,
        })


    total_mb = total_bytes / (1024 * 1024)

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


def _build_status_and_ranking(batch: dict, db) -> dict:
    job_ids = batch["job_ids"]
    jobs = []
    counts = {"queued": 0, "running": 0, "complete": 0, "failed": 0}
    completed: list[tuple[str, dict]] = []

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
            completed.append((job["report_id"], job))

    # One lookup for every finished report, not one per candidate.
    summaries = report_lookup.summaries(
        db, [rid for rid, _ in completed], batch.get("user_id"), _jobs
    )
    ranking = []
    for rid, job in completed:
        summary = summaries.get(rid)
        if not summary:
            continue
        ranking.append({
            "report_id": rid,
            "file_name": as_str(summary.get("file_name")) or job["file_name"],
            "candidate_name": as_str(summary.get("candidate_name")) or "Unknown",
            "overall_score": as_score(summary.get("overall_score")),
            "recommendation": as_str(summary.get("recommendation")) or "manual_review",
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
def bulk_status(
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
def bulk_export_csv(
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
        writer.writerow(safe_row([
            r["rank"], r["candidate_name"], r["file_name"],
            r["overall_score"], r["recommendation"], r["report_id"],
        ]))
    buf.seek(0)

    filename = f"hirelens_ranking_{batch_id[:8]}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class NotifyOverride(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=10_000)


class BulkNotifyRequest(BaseModel):
    """
    One-click send: pass only `decision` and every completed candidate in
    the batch is emailed the default template for that decision.
    Per-candidate overrides let a recruiter customize a specific person's
    message without leaving the "send all" flow — anything not listed in
    `overrides` still goes out with the default template.
    """
    decision: Literal["advance", "schedule_followup", "reject"]
    overrides: dict[str, NotifyOverride] = Field(default_factory=dict, max_length=500)  # report_id -> override
    # Candidates already sent this same decision are skipped unless this is
    # set. A double-click, a retry after a slow response, or a second tab
    # otherwise emailed every candidate in the batch twice.
    resend: bool = False


@router.post("/{batch_id}/notify-all")
async def bulk_notify_all(
    batch_id: str,
    body: BulkNotifyRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Sends a decision-notification email to every candidate in this batch
    who (a) completed analysis and (b) has an email address on file.
    Defaults to the standard template for `decision`; any report_id present
    in `overrides` uses that custom subject/body instead.

    This never touches the saved `recruiter_decision` on each report — it
    only sends email. Recording a decision and notifying the candidate
    remain two independent actions, same as the single-report flow.

    Rate-limited per user (not per batch): this can trigger dozens or
    hundreds of real emails in one call, so a double-click or retry loop
    must not be able to re-blast an entire batch repeatedly.
    """
    from app.services.email.sender import build_decision_email, send_candidate_decision_email

    # body.decision is already constrained to the three valid values by
    # NotifyOverride's Literal type (Pydantic returns 422 automatically
    # for anything else) — no manual re-check needed here.
    check_rate_limit(redis, f"notify-all:{current_user['id']}", settings.NOTIFY_RATE_LIMIT_PER_MINUTE)

    batch = batch_store.get_batch(redis, batch_id)
    if not batch:
        raise NotFoundError(f"Batch '{batch_id}' not found. It may have expired.")
    if batch["user_id"] != current_user["id"]:
        raise ForbiddenError()

    def gather() -> tuple[dict, str, dict]:
        status = _build_status_and_ranking(batch, db)
        sender = directory.get_display_name(
            db, current_user["id"], current_user.get("email") or "The Hiring Team"
        )
        contacts = report_lookup.candidate_contacts(
            db, [r["report_id"] for r in status["ranking"]], current_user["id"], _jobs
        )
        return status, sender, contacts

    # All synchronous I/O; kept off the event loop.
    status, sender_name, contacts = await run_in_threadpool(gather)

    results = []
    newly_notified: list[str] = []
    for r in status["ranking"]:
        report_id = r["report_id"]
        contact = contacts.get(report_id) or {}
        candidate_email = contact.get("email") or ""
        candidate_name = r.get("candidate_name") or contact.get("candidate_name") or "Candidate"

        if not candidate_email:
            results.append({"report_id": report_id, "candidate_name": candidate_name, "email_sent": False, "reason": "no_email_on_file"})
            continue

        if not body.resend and contact.get("notified_decision") == body.decision:
            results.append({"report_id": report_id, "candidate_name": candidate_name, "email_sent": False, "reason": "already_notified"})
            continue

        override = body.overrides.get(report_id)
        if override:
            subject, msg_body = override.subject, override.body
        else:
            draft = build_decision_email(body.decision, candidate_name, sender_name, "HireLens")
            subject, msg_body = draft["subject"], draft["body"]

        sent = await send_candidate_decision_email(
            to_email=str(candidate_email),
            subject=subject,
            body=msg_body,
            reply_to=current_user.get("email") or None,
        )
        results.append({"report_id": report_id, "candidate_name": candidate_name, "email_sent": sent, "reason": None if sent else "provider_unavailable"})
        if sent:
            newly_notified.append(report_id)

    # Recorded only for messages a provider accepted, and in one write.
    if newly_notified and db:
        def record() -> None:
            try:
                db.table("reports").update({
                    "candidate_notified_at": datetime.now(timezone.utc).isoformat(),
                    "candidate_notified_decision": body.decision,
                }).in_("id", newly_notified).eq("user_id", current_user["id"]).execute()
            except Exception as e:
                logger.warning(f"Could not record bulk notification for batch {batch_id}: {e}")

        await run_in_threadpool(record)

    sent_count = sum(1 for x in results if x["email_sent"])
    skipped = sum(1 for x in results if x["reason"] == "already_notified")
    logger.info(
        f"Bulk notify | batch={batch_id} decision={body.decision} "
        f"sent={sent_count}/{len(results)} already_notified={skipped}"
    )

    return {
        "batch_id": batch_id,
        "decision": body.decision,
        "total_candidates": len(results),
        "emails_sent": sent_count,
        "already_notified": skipped,
        "results": results,
    }


@router.get("/{batch_id}/duplicates")
def bulk_duplicate_check(
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
    fulls = report_lookup.full_reports(
        db, [r["report_id"] for r in status["ranking"]], current_user["id"], _jobs
    )
    items = []
    for r in status["ranking"]:
        full = fulls.get(r["report_id"])
        if not full:
            continue
        fingerprint = extract_fingerprint_text(as_dict(full.get("report_data")))
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
