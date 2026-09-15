"""
HireLens — ATS CSV Import API

Recruiters already track candidates in Greenhouse/Lever/Workday/BambooHR/etc.
Re-uploading each resume by hand into HireLens is exactly the busywork this
tool should remove. Every ATS supports exporting the candidate list as CSV
with zero setup (unlike live API integrations, which mostly require a paid
plan + vendor approval) — so that's the import surface for v1.

This endpoint downloads each resume URL found in the CSV (with the same
SSRF guard used elsewhere for resume-derived URLs) and feeds the results
into bulk.py's EXISTING batch pipeline — meaning /api/v1/bulk/{batch_id}/status,
/export.csv, and /duplicates all already work for an ATS-imported batch with
zero extra code, since it's the same batch_store + job runner underneath.
"""

import uuid
import time
import logging
import httpx
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.exceptions import EmptyBatch, TooManyBatches, HireLensException, AllResumesUnreachable
from app.api.v1.endpoints.analysis import (
    _jobs,
    validate_upload,
    _check_rate_limit,
    require_analysis_available,
)
from app.api.v1.endpoints.bulk import _run_batch
from app.services.parser.csv_import import parse_ats_csv
from app.services.verify.ssrf_guard import is_public_http_url
from app.services.queue import batch_store

logger = logging.getLogger("hirelens")
router = APIRouter()

DOWNLOAD_TIMEOUT_SECONDS = 15
MAX_DOWNLOAD_MB = 10


class ResumeDownloadError(HireLensException):
    http_status = 422
    code = "resume_download_failed"


# Redirect hops allowed before giving up — matches certification_verify.py's
# MAX_REDIRECT_HOPS so both SSRF-safe fetchers behave consistently.
_MAX_REDIRECT_HOPS = 3


async def _download_resume(client: httpx.AsyncClient, url: str) -> bytes:
    """
    Downloads a resume URL from an ATS-exported CSV, re-validating the SSRF
    guard on every redirect hop rather than just the original URL.

    This used to call `client.get(url, follow_redirects=True)` after a
    single is_public_http_url() check on the ORIGINAL url — httpx would
    then silently follow any number of redirects, including one pointing
    at a cloud metadata endpoint (e.g. 169.254.169.254) or an internal
    service, without ever re-checking where it actually ended up. A
    malicious/compromised host only has to return a safe-looking URL on
    the first request and a 302 on the follow-up. This mirrors the
    correct pattern already used in certification_verify.py's
    _safe_fetch(): follow_redirects=False + a manual loop that re-runs the
    guard on every Location header before following it.

    Also streams and aborts as soon as MAX_DOWNLOAD_MB is exceeded, rather
    than buffering the full response body first and checking len()
    afterward — the previous version's size check ran only AFTER the
    complete body had already been read into memory, so it didn't actually
    bound memory use against a server returning far more than the cap.
    """
    current_url = url
    max_bytes = MAX_DOWNLOAD_MB * 1024 * 1024

    for _ in range(_MAX_REDIRECT_HOPS + 1):
        if not is_public_http_url(current_url):
            raise ResumeDownloadError(f"Refusing to fetch a non-public/unsafe URL: {current_url[:80]}")

        async with client.stream("GET", current_url, follow_redirects=False) as r:
            if r.is_redirect:
                location = r.headers.get("location")
                if not location:
                    raise ResumeDownloadError("Redirect response had no Location header")
                current_url = str(httpx.URL(current_url).join(location))
                continue

            if not r.is_success:
                raise ResumeDownloadError(f"Download failed with status {r.status_code}")

            chunks = bytearray()
            async for chunk in r.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > max_bytes:
                    raise ResumeDownloadError(f"File exceeds {MAX_DOWNLOAD_MB}MB limit")
            return bytes(chunks)

    raise ResumeDownloadError(f"Too many redirects (max {_MAX_REDIRECT_HOPS}) fetching resume URL")


def _filename_for_row(row: dict) -> str:
    base = (row.get("name") or f"candidate_row{row['row_num']}").strip()
    safe = "".join(c for c in base if c.isalnum() or c in " -_").strip() or f"candidate_row{row['row_num']}"
    return f"{safe}.pdf"


@router.post("/import")
async def ats_import(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="CSV exported from your ATS (Greenhouse, Lever, Workday, etc.)"),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Upload an ATS-exported candidate CSV → HireLens downloads every resume
    URL found in it and analyzes them through the same pipeline as bulk
    upload. Returns immediately with per-row parse results plus a batch_id
    to poll (same endpoints as /api/v1/bulk/{batch_id}/status etc).
    """
    user_id = current_user["id"]

    # This endpoint had NO rate limiting at all before this fix — every
    # other expensive upload path (analysis, bulk, match) at least called
    # _check_rate_limit, even though that function itself had its own bug
    # (see the C-06 fix in analysis.py). ATS import can trigger up to
    # BULK_MAX_FILES downloads + full analyses per call, so it's at least
    # as expensive as bulk upload and needs the same guard.
    require_analysis_available()
    _check_rate_limit(redis, user_id)

    contents = await file.read()
    if not contents:
        raise EmptyBatch()

    parsed = parse_ats_csv(contents)
    if not parsed["rows"]:
        raise EmptyBatch()

    active = batch_store.count_active_batches(redis, user_id)
    if active >= settings.BULK_MAX_CONCURRENT_BATCHES_PER_USER:
        raise TooManyBatches(settings.BULK_MAX_CONCURRENT_BATCHES_PER_USER)

    download_results = []
    valid_items = []
    job_ids = []

    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS) as client:
        for row in parsed["rows"]:
            job_id = str(uuid.uuid4())
            filename = _filename_for_row(row)

            try:
                content = await _download_resume(client, row["resume_url"])
                effective_mime = validate_upload(content, filename, "application/pdf")
            except Exception as e:
                message = getattr(e, "message", str(e))
                job_ids.append(job_id)
                _jobs[job_id] = {
                    "id": job_id, "user_id": user_id, "batch_id": None,
                    "status": "failed", "stage": "failed", "progress": 0,
                    "file_name": filename, "report_id": None,
                    "error": f"Row {row['row_num']}: {message}",
                    "created_at": time.time(),
                }
                download_results.append({"row_num": row["row_num"], "status": "failed", "reason": message})
                continue

            job_ids.append(job_id)
            _jobs[job_id] = {
                "id": job_id, "user_id": user_id, "batch_id": None,
                "status": "queued", "stage": "queued", "progress": 0,
                "file_name": filename, "report_id": None, "error": None,
                "created_at": time.time(),
            }
            valid_items.append({"job_id": job_id, "bytes": content, "mime": effective_mime, "filename": filename})
            download_results.append({"row_num": row["row_num"], "status": "queued"})

    if not valid_items:
        for jid in job_ids:
            _jobs.pop(jid, None)
        raise AllResumesUnreachable()

    batch_id = str(uuid.uuid4())
    for jid in job_ids:
        if jid in _jobs:
            _jobs[jid] = {**_jobs[jid], "batch_id": batch_id}

    batch_store.create_batch(redis, batch_id, user_id, job_ids, total=len(job_ids))

    logger.info(
        f"ATS import batch created | id={batch_id} user={user_id} "
        f"rows={len(parsed['rows'])} valid={len(valid_items)} skipped={len(parsed['skipped'])}"
    )

    background_tasks.add_task(
        _run_batch, batch_id=batch_id, user_id=user_id,
        valid_items=valid_items, db=db, redis=redis,
    )

    return {
        "batch_id": batch_id,
        "detected_columns": parsed["detected_columns"],
        "total_rows": len(parsed["rows"]) + len(parsed["skipped"]),
        "queued": len(valid_items),
        "skipped_at_parse": parsed["skipped"],
        "skipped_at_download": [r for r in download_results if r["status"] == "failed"],
        "message": (
            f"Queued {len(valid_items)} resumes from this CSV. Poll "
            f"/api/v1/bulk/{batch_id}/status — the same status/ranking/export/"
            f"duplicates endpoints as a regular bulk upload all work here."
        ),
    }
