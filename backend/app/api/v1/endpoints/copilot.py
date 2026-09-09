"""
HireLens — Candidate Interview Co-Pilot & Custom Probe API (Feature A)
Allows recruiters to run live candidate interviews, customize probe questions,
score candidate competencies (technical depth, culture fit, problem solving),
and store structured interviewer notes.
"""

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError, PersistenceError
from app.api.v1.endpoints.analysis import _jobs
from app.services.teams.access import user_can_access_report

logger = logging.getLogger("hirelens")
router = APIRouter()

# In-memory fallback store for co-pilot evaluations when DB is unconfigured
# Key: report_id -> copilot data dict
_copilot_store: dict[str, dict] = {}


class CustomQuestion(BaseModel):
    id: str | None = None
    question: str = Field(..., min_length=5, max_length=500)
    category: str = "custom"
    rationale: str | None = None
    is_asked: bool = False
    notes: str | None = None


class CompetencyScore(BaseModel):
    category: str  # technical, problem_solving, culture_fit, authenticity
    score: int = Field(..., ge=1, le=5)  # 1 to 5 scale
    notes: str | None = None


class CoPilotSaveRequest(BaseModel):
    scorecard: list[CompetencyScore] = Field(default_factory=list)
    custom_questions: list[CustomQuestion] = Field(default_factory=list)
    interview_notes: str | None = Field(None, max_length=5000)
    recommendation_override: str | None = None  # advance, reject, follow_up


@router.get("/{report_id}/copilot", tags=["Interview Co-Pilot"])
async def get_copilot_data(
    report_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Retrieve saved interview co-pilot notes, scorecard, and custom questions."""
    if db:
        try:
            res = (
                db.table("reports")
                .select("id,user_id,report_data")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
            if res and res.data:
                if not user_can_access_report(db, res.data, current_user["id"]):
                    raise NotFoundError(f"Report '{report_id}' not found.")
                report_data = res.data.get("report_data") or {}
                copilot_data = report_data.get("copilot_data") or _copilot_store.get(report_id) or {}
                return {"report_id": report_id, "copilot": copilot_data}
        except Exception as e:
            logger.warning(f"Co-pilot DB get failed for report {report_id}: {e}")

    # Fallback in-memory lookup
    mem_report = _jobs.get(f"report_{report_id}")
    if mem_report and mem_report.get("_owner_user_id") == current_user["id"]:
        copilot_data = mem_report.get("copilot_data") or _copilot_store.get(report_id) or {}
        return {"report_id": report_id, "copilot": copilot_data}

    stored = _copilot_store.get(report_id)
    if stored:
        return {"report_id": report_id, "copilot": stored}

    return {"report_id": report_id, "copilot": {}}


@router.post("/{report_id}/copilot", tags=["Interview Co-Pilot"])
async def save_copilot_data(
    report_id: str,
    body: CoPilotSaveRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Save live interview scorecard ratings, custom questions, and notes.

    This used to unconditionally write to the in-memory `_copilot_store`
    keyed by the raw `report_id` string *before* any DB or ownership check
    ran, and always returned `{"status": "ok"}` regardless of whether that
    write actually reached anywhere real. Two consequences: (1) if Supabase
    was configured but the update failed or matched no row (wrong id, or a
    report owned by someone else), the recruiter was told "saved" when
    nothing durable happened; (2) with no DB, ANY authenticated recruiter
    could write co-pilot notes onto ANY report_id by guessing or
    enumerating it — there was no ownership check on this path at all,
    unlike the read side (get_copilot_data) which does check. Both are
    fixed below: a write is only accepted once ownership is confirmed
    (via DB or the in-memory job record), and `saved` accurately reflects
    whether it reached a real store.
    """
    payload = {
        "scorecard": [s.model_dump() for s in body.scorecard],
        "custom_questions": [q.model_dump() for q in body.custom_questions],
        "interview_notes": body.interview_notes,
        "recommendation_override": body.recommendation_override,
        "updated_by": current_user["id"],
        "updated_at": __import__("time").time(),
    }

    saved = False
    found = False

    if db:
        try:
            res = (
                db.table("reports")
                .select("id,user_id,team_id,report_data")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
            if res and res.data:
                found = True
                if not user_can_access_report(db, res.data, current_user["id"]):
                    raise NotFoundError(f"Report '{report_id}' not found.")

                report_data = dict(res.data.get("report_data") or {})
                report_data["copilot_data"] = payload

                upd = db.table("reports").update({"report_data": report_data}).eq("id", report_id).execute()
                saved = bool(upd.data)
        except NotFoundError:
            raise
        except Exception as e:
            logger.warning(f"Co-pilot DB save failed for report {report_id}: {e}")

    if not saved:
        mem_report = _jobs.get(f"report_{report_id}")
        if mem_report:
            found = True
            if mem_report.get("_owner_user_id") != current_user["id"]:
                raise NotFoundError(f"Report '{report_id}' not found.")
            mem_report["copilot_data"] = payload
            _copilot_store[report_id] = payload
            saved = True

    if not saved and not found:
        # The report doesn't resolve anywhere this recruiter can access —
        # refuse rather than silently accepting notes into the void (and
        # rather than letting anyone stash data under an arbitrary id).
        raise NotFoundError(f"Report '{report_id}' not found.")

    if not saved:
        # `found` but not `saved`: the report row exists and this recruiter
        # may access it, but the UPDATE came back empty (the row changed
        # under us, a write policy rejected it, PostgREST returned no
        # representation) and there was no in-memory job to fall back on.
        #
        # The previous version of this function fell straight through to the
        # `{"status": "ok"}` below in exactly this case — which is the same
        # "told the user it saved when nothing persisted" bug the docstring
        # above describes fixing, still live on one branch. An interviewer
        # who types up a full scorecard mid-interview and sees "Saved" must
        # never lose it silently; failing loudly lets them retry or copy it
        # out while it's still on screen.
        logger.error(
            f"Co-pilot save reached no durable store | report={report_id} "
            f"user={current_user['id']} (row found but update persisted nothing)"
        )
        raise PersistenceError(
            "Could not save the evaluation. Please retry — your notes are still on screen."
        )

    logger.info(f"Co-pilot data saved | report={report_id} user={current_user['id']}")
    return {"status": "ok", "report_id": report_id, "copilot": payload}
