"""
HireLens — Public Data Verification API (Feature 3)

POST /api/v1/verify/{report_id}/run runs four independent, real-time
public-data checks concurrently and merges the result into the report's
report_data JSON (no schema migration needed — same jsonb column pattern
as JD match in Feature 2):

  - github        → live GitHub public API skill cross-check
  - education     → free university-domain registry lookup
  - certifications→ live-fetch of any public verify link found in resume text
  - experience    → best-effort employer domain check

Every sub-check is isolated with asyncio.gather(..., return_exceptions=True)
so one failing check (network blip, rate limit, etc.) never breaks the others.
"""

import logging
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError, ForbiddenError
from app.api.v1.endpoints.analysis import _jobs
from app.services.verify.github_verify import verify_github, extract_username
from app.services.verify.education_verify import verify_education
from app.services.verify.certification_verify import verify_certifications
from app.services.verify.company_verify import verify_experience_companies

logger = logging.getLogger("hirelens")
router = APIRouter()


class VerifyRequest(BaseModel):
    github_username: str | None = None  # recruiter override if resume has none / a wrong one


def _load_report(report_id: str, user_id: str, db) -> tuple[dict, str]:
    """Returns (report_dict, source) where source is 'db' or 'memory' — needed
    so we persist the verification result back to wherever it actually lives."""
    if db:
        try:
            result = db.table("reports").select("*").eq("id", report_id).maybe_single().execute()
            if result.data:
                row = result.data
                if row["user_id"] != user_id:
                    raise ForbiddenError()
                report = dict(row.get("report_data") or {})
                report["id"] = report_id
                report["file_name"] = row.get("file_name") or report.get("file_name", "")
                return report, "db"
        except ForbiddenError:
            raise
        except Exception as e:
            logger.warning(f"DB fetch failed for report {report_id}: {e}")

    data = _jobs.get(f"report_{report_id}")
    if data:
        return data, "memory"

    raise NotFoundError(f"Report '{report_id}' not found.")


def _persist_verification(report_id: str, user_id: str, report: dict, source: str, db) -> None:
    if source == "db" and db:
        try:
            db.table("reports").update({"report_data": report}).eq("id", report_id).eq("user_id", user_id).execute()
            return
        except Exception as e:
            logger.warning(f"Failed to persist verification for report {report_id} to DB: {e}")
    # Always mirror to in-memory too, so it's available even if the DB write above failed.
    _jobs[f"report_{report_id}"] = report


def _safe(result, fallback):
    return fallback if isinstance(result, BaseException) else result


@router.post("/{report_id}/run")
async def run_verification(
    report_id: str,
    body: VerifyRequest = VerifyRequest(),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Runs all four public-data verification checks in parallel and stores
    the result on the report. Safe to re-run — it overwrites the previous
    verification with a fresh one.
    """
    report, source = _load_report(report_id, current_user["id"], db)

    candidate = report.get("candidate") or {}
    skills = report.get("skills") or {}
    claimed_skills = list(skills.get("all_claimed") or skills.get("technical") or [])

    username = body.github_username or extract_username(candidate.get("github") or candidate.get("github_url"))

    github_res, edu_res, cert_res, exp_res = await asyncio.gather(
        verify_github(username, claimed_skills),
        verify_education(list(report.get("education") or [])),
        verify_certifications(list(report.get("certifications") or []), candidate.get("name")),
        verify_experience_companies(list(report.get("experience") or [])),
        return_exceptions=True,
    )

    verification = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "github": _safe(github_res, {"status": "error", "note": "GitHub verification failed unexpectedly."}),
        "education": _safe(edu_res, []),
        "certifications": _safe(cert_res, []),
        "experience": _safe(exp_res, []),
    }

    for label, res in (("github", github_res), ("education", edu_res), ("certifications", cert_res), ("experience", exp_res)):
        if isinstance(res, BaseException):
            logger.warning(f"[verify {report_id}] {label} check failed: {res}")

    report["verification"] = verification
    _persist_verification(report_id, current_user["id"], report, source, db)

    logger.info(f"Verification run | report={report_id} user={current_user['id']} github_status={verification['github'].get('status')}")

    return verification


@router.get("/{report_id}")
async def get_verification(
    report_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Returns the last verification result for a report, if one has been run."""
    report, _ = _load_report(report_id, current_user["id"], db)
    verification = report.get("verification")
    if not verification:
        raise NotFoundError("No verification has been run for this report yet.")
    return verification
