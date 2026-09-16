"""
HireLens — Candidate Interview Co-Pilot & Custom Probe API (Feature A)
Allows recruiters to run live candidate interviews, customize probe questions,
score candidate competencies (technical depth, culture fit, problem solving),
and store structured interviewer notes.
"""

import logging
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError, HireLensException
from app.api.v1.endpoints.analysis import _jobs
from app.core import local_db
from app.services.teams.access import user_can_access_report

logger = logging.getLogger("hirelens")
router = APIRouter()

# NOTE: the module-level `_copilot_store` dict that used to live here is
# gone. It was keyed by report id with no owner in the key and no ownership
# check on the read path, which made it a cross-tenant leak (see
# _assert_can_access below). Co-pilot data now lives with the report it
# belongs to, in Supabase and/or the local SQLite store.


class CustomQuestion(BaseModel):
    id: str | None = None
    question: str = Field(..., min_length=5, max_length=500)
    category: str = "custom"
    rationale: str | None = None
    is_asked: bool = False
    notes: str | None = None


class CompetencyScore(BaseModel):
    category: str  # technical_depth, problem_solving, culture_fit, authenticity
    # 0 means "not yet rated", 1-5 is the rating.
    #
    # This used to be ge=1, which made a partially-filled scorecard
    # unsaveable — and a partially-filled scorecard is the normal case. The
    # UI starts every category unrated and lets an interviewer clear a rating
    # by clicking it again, so any save before all four were rated returned
    # 422 and silently discarded the interviewer's notes along with it,
    # mid-interview, with no indication of which field was at fault.
    score: int = Field(0, ge=0, le=5)
    notes: str | None = Field(None, max_length=2000)


class CoPilotSaveRequest(BaseModel):
    scorecard: list[CompetencyScore] = Field(default_factory=list)
    custom_questions: list[CustomQuestion] = Field(default_factory=list)
    interview_notes: str | None = Field(None, max_length=5000)
    recommendation_override: str | None = None  # advance, reject, follow_up


def _assert_can_access(report_id: str, user_id: str, db) -> None:
    """
    Raise NotFoundError unless `user_id` may see this report.

    SECURITY: every co-pilot path must go through this before touching
    stored data. The previous implementation keyed an in-memory dict by
    report id alone and checked ownership on *some* branches only:

      * GET fell through to `_copilot_store.get(report_id)` with no check at
        all, so any authenticated user could read another recruiter's
        private interview notes by guessing or obtaining a report id;
      * POST wrote `_copilot_store[report_id]` as its first statement,
        before any check, so any authenticated user could overwrite them.

    Interview notes routinely contain compensation expectations and candid
    assessments, so this was a cross-tenant leak of the most sensitive data
    in the product.
    """
    if db:
        try:
            res = (
                db.table("reports")
                .select("id,user_id,team_id")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
            if res and res.data:
                if not user_can_access_report(db, res.data, user_id):
                    raise NotFoundError(f"Report '{report_id}' not found.")
                return
        except NotFoundError:
            raise
        except Exception as e:
            logger.warning(f"Co-pilot access check via DB failed for {report_id}: {e}")

    # Local path: the in-process copy first, then the durable store.
    mem_report = _jobs.get(f"report_{report_id}")
    if mem_report is not None:
        if mem_report.get("_owner_user_id") != user_id:
            raise NotFoundError(f"Report '{report_id}' not found.")
        return

    if local_db.get_report(report_id, user_id) is not None:
        return

    raise NotFoundError(f"Report '{report_id}' not found.")


@router.get("/{report_id}/copilot", tags=["Interview Co-Pilot"])
async def get_copilot_data(
    report_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Retrieve saved interview co-pilot notes, scorecard, and custom questions."""
    user_id = current_user["id"]
    _assert_can_access(report_id, user_id, db)

    if db:
        try:
            res = (
                db.table("reports")
                .select("report_data")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
            if res and res.data:
                data = (res.data.get("report_data") or {}).get("copilot_data")
                if data:
                    return {"report_id": report_id, "copilot": data}
        except Exception as e:
            logger.warning(f"Co-pilot DB get failed for report {report_id}: {e}")

    mem_report = _jobs.get(f"report_{report_id}")
    if mem_report and mem_report.get("copilot_data"):
        return {"report_id": report_id, "copilot": mem_report["copilot_data"]}

    persisted = local_db.get_copilot(report_id, user_id)
    if persisted:
        return {"report_id": report_id, "copilot": persisted}

    return {"report_id": report_id, "copilot": {}}


@router.post("/{report_id}/copilot", tags=["Interview Co-Pilot"])
async def save_copilot_data(
    report_id: str,
    body: CoPilotSaveRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Save live interview scorecard ratings, custom questions, and notes."""
    user_id = current_user["id"]
    _assert_can_access(report_id, user_id, db)

    payload = {
        "scorecard": [s.model_dump() for s in body.scorecard],
        "custom_questions": [q.model_dump() for q in body.custom_questions],
        "interview_notes": body.interview_notes,
        "recommendation_override": body.recommendation_override,
        "updated_by": user_id,
        "updated_at": time.time(),
    }

    saved = False

    if db:
        try:
            res = (
                db.table("reports")
                .select("report_data")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
            if res and res.data:
                report_data = dict(res.data.get("report_data") or {})
                report_data["copilot_data"] = payload
                db.table("reports").update({"report_data": report_data}).eq("id", report_id).execute()
                saved = True
        except Exception as e:
            logger.warning(f"Co-pilot DB save failed for report {report_id}: {e}")

    # Durable local store — this is what survives a restart. The in-memory
    # copy below is only a cache for this process.
    if local_db.save_copilot(report_id, user_id, payload):
        saved = True

    mem_report = _jobs.get(f"report_{report_id}")
    if mem_report is not None:
        mem_report["copilot_data"] = payload
        saved = True

    if not saved:
        raise HireLensException(
            "Could not save your interview notes. Please try again."
        )

    logger.info(f"Co-pilot data saved | report={report_id} user={user_id}")
    return {"status": "ok", "report_id": report_id, "copilot": payload}
