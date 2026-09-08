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

import hashlib
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.cache import cache_get, cache_set
from app.core.rate_limit import check_rate_limit
from app.core.exceptions import NotFoundError, ForbiddenError
from app.api.v1.endpoints.analysis import _jobs
from app.services.verify.github_verify import verify_github, extract_username
from app.services.verify.education_verify import verify_education
from app.services.verify.certification_verify import verify_certifications
from app.services.verify.company_verify import verify_experience_companies
from app.services.verify.trust_assessment import compute_trust_assessment

logger = logging.getLogger("hirelens")
router = APIRouter()

# Per-user cap on verification runs.
#
# This is by far the most expensive endpoint in the app: every call fans out
# to FOUR concurrent outbound HTTP checks (GitHub API, a university-domain
# registry, a live fetch of each certification link found in the resume, and
# an employer-domain probe), each with a VERIFY_TIMEOUT_SECONDS budget. It had
# no limit at all, which meant one authenticated account looping it could:
#
#   - saturate the event loop of a single-worker free-tier container and make
#     the API unresponsive for every other recruiter;
#   - burn the shared GitHub API quota (60/hr unauthenticated, 5000/hr with a
#     token) that every user's verification depends on;
#   - use the server as an outbound request amplifier against third parties,
#     since certification links come from candidate-supplied resume text.
#
# Signup is open, so "authenticated" is not a meaningful barrier here.
#
# The number is chosen to be invisible in real use — a recruiter verifies a
# report once, occasionally re-runs it after pasting a corrected GitHub
# username — while cutting an automated loop dead.
VERIFY_RUNS_PER_MINUTE = 10
VERIFY_RUNS_PER_HOUR = 60


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

    # In-memory fallback path. This MUST enforce the same ownership check as
    # the DB path above — reports written here are stamped with
    # `_owner_user_id` at creation time (see analysis.py's _run_analysis).
    # A report with no owner stamp at all (shouldn't happen for anything
    # written after this fix, but may exist from an older in-flight job)
    # is treated as inaccessible rather than open-to-anyone, since "we
    # can't tell who owns this" must fail closed, not open.
    data = _jobs.get(f"report_{report_id}")
    if data:
        owner = data.get("_owner_user_id")
        if owner is None or owner != user_id:
            raise ForbiddenError()
        return data, "memory"

    raise NotFoundError(f"Report '{report_id}' not found.")


def _persist_verification(report_id: str, user_id: str, report: dict, source: str, db, top_level_updates: dict | None = None) -> None:
    if source == "db" and db:
        try:
            payload = {"report_data": report}
            if top_level_updates:
                payload.update(top_level_updates)
            db.table("reports").update(payload).eq("id", report_id).eq("user_id", user_id).execute()
            return
        except Exception as e:
            logger.warning(f"Failed to persist verification for report {report_id} to DB: {e}")
    # Always mirror to in-memory too, so it's available even if the DB write above failed.
    #
    # Defensively (re-)stamp the owner here regardless of `source`. If this
    # report originally came from the DB (source == "db") and the DB write
    # just failed, this dict has never had `_owner_user_id` set — without
    # this line, it would land in `_jobs` unstamped, which the in-memory
    # read path in this file and in reports.py both treat as "nobody owns
    # this" and therefore refuse to serve to anyone. Stamping it here keeps
    # it accessible to its actual owner instead of orphaning it.
    report["_owner_user_id"] = user_id
    _jobs[f"report_{report_id}"] = report


def _safe(result, fallback):
    return fallback if isinstance(result, BaseException) else result


GITHUB_VERIFY_CACHE_TTL_SECONDS = 3600  # 1 hour — see app/core/cache.py


async def _cached_verify_github(redis, username: str | None, claimed_skills: list[str]) -> dict:
    """
    Wraps verify_github() with a short Redis cache keyed on the username +
    the exact claimed-skills set, so re-verifying the same candidate (a
    recruiter double-checking, or a second teammate opening the same
    report) doesn't re-spend GitHub API rate-limit budget for an answer
    that's still fresh. A no-username call is never cached — there's
    nothing to key it on, and it's already free (no network call).
    """
    if not username:
        return await verify_github(username, claimed_skills)

    skills_fingerprint = hashlib.sha256(
        ",".join(sorted(s.lower().strip() for s in claimed_skills)).encode()
    ).hexdigest()[:16]
    cache_key = f"github_verify:{username.lower()}:{skills_fingerprint}"

    cached = cache_get(redis, cache_key)
    if cached is not None:
        return cached

    result = await verify_github(username, claimed_skills)
    # Don't cache transient failures — a rate-limit or network blip should
    # be retried on the next run, not frozen into the cache for an hour.
    if result.get("status") not in ("error", "rate_limited"):
        cache_set(redis, cache_key, result, GITHUB_VERIFY_CACHE_TTL_SECONDS)
    return result


RECOMMENDATION_RANK = {"recommended": 2, "manual_review": 1, "high_risk": 0}
RANK_TO_RECOMMENDATION = {v: k for k, v in RECOMMENDATION_RANK.items()}


def _apply_verification_to_recommendation(report: dict, trust: dict) -> dict | None:
    """
    The AI's initial recommendation is set BEFORE verification ever runs —
    so strong real-world evidence uncovered by verification (e.g. the
    candidate's claimed GitHub account doesn't exist) previously never fed
    back into the headline recommendation shown on the dashboard/rankings,
    even though it's exactly the kind of signal that should change a
    recruiter's read on a candidate.

    Deliberately asymmetric and conservative:
    - DOWNGRADE by one level (recommended → manual_review → high_risk) when
      trust_assessment comes back "low_confidence" — strong negative
      evidence should be able to override a good AI score.
    - NEVER auto-upgrade on "high_confidence" — the AI may have flagged
      genuine concerns (timeline gaps, inconsistent claims) that
      verification doesn't check at all, and verification passing doesn't
      resolve those.

    Returns a dict of top-level DB columns to update if a change was made,
    else None. Also mutates report["credibility"] in place so the JSON blob
    and the returned report stay consistent with each other.
    """
    cred = report.get("credibility") or {}
    current = cred.get("recommendation", "manual_review")
    if current not in RECOMMENDATION_RANK:
        return None

    if trust.get("verdict") != "low_confidence" or not trust.get("evidence_available"):
        return None

    current_rank = RECOMMENDATION_RANK[current]
    if current_rank == 0:
        return None  # already high_risk, nothing lower to downgrade to

    new_recommendation = RANK_TO_RECOMMENDATION[current_rank - 1]

    cred["ai_recommendation"] = cred.get("ai_recommendation", current)  # preserve original, first downgrade only
    cred["recommendation"] = new_recommendation
    cred["recommendation_adjusted_by_verification"] = True
    cred["recommendation_adjustment_reason"] = (
        "Downgraded from the AI's initial read after public-data verification "
        "found strong contradicting evidence — see the Verify tab for details."
    )
    report["credibility"] = cred

    return {"recommendation": new_recommendation}


@router.post("/{report_id}/run")
async def run_verification(
    report_id: str,
    body: VerifyRequest = VerifyRequest(),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Runs all four public-data verification checks in parallel and stores
    the result on the report. Safe to re-run — it overwrites the previous
    verification with a fresh one (GitHub is served from a short cache
    when re-run for the same username + skills; see _cached_verify_github).
    """
    # Both windows: the per-minute cap stops a tight loop, the per-hour cap
    # stops a slow drip that would stay under it all day.
    user_id = current_user["id"]
    check_rate_limit(redis, f"verify-run:{user_id}", VERIFY_RUNS_PER_MINUTE, window_seconds=60)
    check_rate_limit(redis, f"verify-run-hr:{user_id}", VERIFY_RUNS_PER_HOUR, window_seconds=3600)

    report, source = _load_report(report_id, current_user["id"], db)

    candidate = report.get("candidate") or {}
    skills = report.get("skills") or {}
    claimed_skills = list(skills.get("all_claimed") or skills.get("technical") or [])

    username = body.github_username or extract_username(candidate.get("github") or candidate.get("github_url"))

    github_res, edu_res, cert_res, exp_res = await asyncio.gather(
        _cached_verify_github(redis, username, claimed_skills),
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

    trust = compute_trust_assessment(
        ai_content_analysis=report.get("ai_content_analysis"),
        verification=verification,
        overall_score=int((report.get("credibility") or {}).get("overall") or 0),
    )
    verification["trust_assessment"] = trust
    logger.info(f"[verify {report_id}] trust_assessment={trust['verdict']} score={trust['score']}")

    report["verification"] = verification
    top_level_updates = _apply_verification_to_recommendation(report, trust)
    if top_level_updates:
        logger.warning(
            f"[verify {report_id}] recommendation downgraded to "
            f"'{top_level_updates['recommendation']}' based on verification evidence"
        )
    _persist_verification(report_id, current_user["id"], report, source, db, top_level_updates)

    logger.info(f"Verification run | report={report_id} user={current_user['id']} github_status={verification['github'].get('status')}")

    verification["recommendation_update"] = (
        {
            "new_recommendation": top_level_updates["recommendation"],
            "ai_recommendation": report["credibility"].get("ai_recommendation"),
            "reason": report["credibility"].get("recommendation_adjustment_reason"),
        }
        if top_level_updates else None
    )

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
