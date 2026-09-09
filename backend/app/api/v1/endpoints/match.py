"""
HireLens — Job Description Match API (Feature 2)

HR pastes/uploads a Job Description + multiple CVs. Each CV goes through the
SAME parse → credibility-analysis pipeline as bulk upload (Feature 1), then
one extra lightweight AI call scores it against the JD using the
already-extracted skills/experience (no re-parsing, no wasted tokens).

Reuses Feature 1's infra almost entirely:
- _jobs / _run_analysis from analysis.py (via the new post_process hook)
- batch_store for the Redis-backed batch registry
- the same asyncio.Semaphore concurrency pattern
"""

import io
import csv
import uuid
import asyncio
import logging
from functools import partial
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from app.core.csv_safety import csv_safe_row
from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.exceptions import (
    NotFoundError, ForbiddenError, EmptyBatch, TooManyFiles,
    TooManyBatches, FileTooLarge, InvalidJobDescription,
)
from app.api.v1.endpoints.analysis import _jobs, _run_analysis, _check_rate_limit, _cleanup_old_jobs, validate_upload
from app.services.ai.engine import engine
from app.services.parser.document_parser import extract_text
from app.services.queue import batch_store

logger = logging.getLogger("hirelens")
router = APIRouter()

_match_semaphore = asyncio.Semaphore(settings.BULK_CONCURRENCY)


async def _resolve_jd_text(jd_text: str | None, jd_file: UploadFile | None) -> str:
    """Accepts either pasted JD text or an uploaded JD file (PDF/DOCX/TXT)."""
    if jd_text and jd_text.strip():
        text = jd_text.strip()
    elif jd_file is not None:
        contents = await jd_file.read()
        if not contents:
            raise InvalidJobDescription()
        filename = (jd_file.filename or "").lower()
        mime = (jd_file.content_type or "").lower()
        if filename.endswith(".txt") or mime.startswith("text/"):
            text = contents.decode("utf-8", errors="ignore").strip()
        else:
            try:
                text = extract_text(contents, mime, filename).strip()
            except Exception as e:
                raise InvalidJobDescription() from e
    else:
        raise InvalidJobDescription()

    if len(text) < 30:
        raise InvalidJobDescription()

    return text[: settings.JD_MAX_CHARS]


@router.post("/upload", status_code=202)
async def match_upload(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(..., description=f"Up to {settings.BULK_MAX_FILES} PDF/DOCX resumes"),
    jd_text: str | None = Form(None, description="Job description pasted as text"),
    jd_file: UploadFile | None = File(None, description="Job description as PDF/DOCX/TXT"),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Upload a JD (text or file) + many resumes → returns batch_id immediately.
    Poll GET /api/v1/match/{batch_id}/status for live progress + JD-match ranking.
    """
    if len(_jobs) > 200:
        _cleanup_old_jobs()
    batch_store.cleanup_old_batches()

    user_id = current_user["id"]
    resolved_jd = await _resolve_jd_text(jd_text, jd_file)

    if not files:
        raise EmptyBatch()
    if len(files) > settings.BULK_MAX_FILES:
        raise TooManyFiles(settings.BULK_MAX_FILES)

    active = batch_store.count_active_batches(redis, user_id)
    if active >= settings.BULK_MAX_CONCURRENT_BATCHES_PER_USER:
        raise TooManyBatches(settings.BULK_MAX_CONCURRENT_BATCHES_PER_USER)

    _check_rate_limit(redis, user_id)

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
        f"JD match batch created | id={batch_id} user={user_id} files={len(files)} "
        f"valid={len(valid_items)} jd_len={len(resolved_jd)}"
    )

    background_tasks.add_task(
        _run_match_batch, batch_id=batch_id, user_id=user_id,
        valid_items=valid_items, jd_text=resolved_jd, db=db, redis=redis,
    )

    return {
        "batch_id": batch_id,
        "total": len(files),
        "accepted": len(valid_items),
        "rejected": len(files) - len(valid_items),
        "message": f"Matching {len(valid_items)} resumes against the job description.",
    }


async def _jd_post_process(result: dict, jd_text: str) -> dict:
    """Runs after credibility analysis, before storage — attaches jd_match."""
    try:
        match = await engine.match_jd(result, jd_text)
    except Exception as e:
        logger.warning(f"JD match failed, storing report without it: {e}")
        match = {
            "match_percent": 0, "matching_skills": [], "missing_skills": [],
            "verdict": "unknown", "rationale": "JD match could not be computed.",
        }
    result["jd_match"] = match
    return result


async def _run_match_batch(batch_id: str, user_id: str, valid_items: list[dict], jd_text: str, db, redis):
    async def run_one(item: dict):
        async with _match_semaphore:
            await _run_analysis(
                job_id=item["job_id"],
                user_id=user_id,
                file_bytes=item["bytes"],
                mime_type=item["mime"],
                filename=item["filename"],
                db=db,
                post_process=partial(_jd_post_process, jd_text=jd_text),
            )

    try:
        await asyncio.gather(*(run_one(it) for it in valid_items), return_exceptions=True)
    finally:
        batch_store.release_batch(redis, user_id, batch_id)
        logger.info(f"[match batch {batch_id}] all jobs finished")


def _get_report_full(report_id: str, db) -> dict | None:
    """Fetches file_name/candidate/score + the full report_data JSON (needed for jd_match)."""
    if db:
        try:
            res = (
                db.table("reports")
                .select("id,file_name,candidate_name,overall_score,recommendation,report_data")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
            if res.data:
                return res.data
        except Exception as e:
            logger.warning(f"Match ranking DB lookup failed for {report_id}: {e}")

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
            "report_data": data,
        }
    return None


def _build_match_status(batch: dict, db) -> dict:
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
            full = _get_report_full(job["report_id"], db)
            if full:
                rd = full.get("report_data") or {}
                jd = rd.get("jd_match") or {}
                ranking.append({
                    "report_id": job["report_id"],
                    "file_name": full.get("file_name") or job["file_name"],
                    "candidate_name": full.get("candidate_name") or "Unknown",
                    "overall_score": int(full.get("overall_score") or 0),
                    "recommendation": full.get("recommendation") or "manual_review",
                    "match_percent": int(jd.get("match_percent") or 0),
                    "matching_skills": list(jd.get("matching_skills") or []),
                    "missing_skills": list(jd.get("missing_skills") or []),
                    "verdict": jd.get("verdict") or "unknown",
                    "rationale": jd.get("rationale") or "",
                })

    ranking.sort(key=lambda r: r["match_percent"], reverse=True)
    for i, r in enumerate(ranking, start=1):
        r["rank"] = i
        r["is_best_fit"] = (i == 1)

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
async def match_status(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    batch = batch_store.get_batch(redis, batch_id)
    if not batch:
        raise NotFoundError(f"Batch '{batch_id}' not found. It may have expired.")
    if batch["user_id"] != current_user["id"]:
        raise ForbiddenError()

    return _build_match_status(batch, db)


@router.get("/{batch_id}/export.csv")
async def match_export_csv(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    batch = batch_store.get_batch(redis, batch_id)
    if not batch:
        raise NotFoundError(f"Batch '{batch_id}' not found. It may have expired.")
    if batch["user_id"] != current_user["id"]:
        raise ForbiddenError()

    result = _build_match_status(batch, db)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Rank", "Candidate Name", "File Name", "Match %", "Verdict",
        "Overall Credibility Score", "Missing Skills", "Report ID",
    ])
    for r in result["ranking"]:
        # See app/core/csv_safety.py. missing_skills is included: it is also
        # LLM-derived from the resume and the job description.
        writer.writerow(csv_safe_row([
            r["rank"], r["candidate_name"], r["file_name"], r["match_percent"],
            r["verdict"], r["overall_score"], "; ".join(r["missing_skills"]), r["report_id"],
        ]))
    buf.seek(0)

    filename = f"hirelens_jd_match_{batch_id[:8]}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
