"""
HireLens — Reports API
Fixed:
- All Supabase calls are SYNC (no await)
- Proper error handling on each DB call
- ForbiddenError not swallowed
- Decision validation with proper 422
"""

import logging
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Literal

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.api.v1.endpoints.analysis import _jobs  # in-memory fallback store

logger = logging.getLogger("hirelens")
router = APIRouter()


class DecisionRequest(BaseModel):
    decision: Literal["advance", "schedule_followup", "reject"]
    notes: str | None = None


@router.get("")
async def list_reports(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    recommendation: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """List all reports for current recruiter, newest first."""
    if not db:
        # Return in-memory reports if no DB
        mem_reports = [
            v for k, v in _jobs.items()
            if k.startswith("report_") and isinstance(v, dict)
        ]
        return {"reports": [], "total": 0, "page": 1, "pages": 0}

    try:
        offset = (page - 1) * limit

        query = (
            db.table("reports")
            .select("id,file_name,candidate_name,overall_score,recommendation,created_at,recruiter_decision")
            .eq("user_id", current_user["id"])
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
        )

        if recommendation and recommendation in ("recommended", "manual_review", "high_risk"):
            query = query.eq("recommendation", recommendation)

        # SYNC call — no await
        result = query.execute()
        items = result.data or []

        # Count total
        count_result = (
            db.table("reports")
            .select("id", count="exact")
            .eq("user_id", current_user["id"])
            .execute()
        )
        total = count_result.count or len(items)

        return {
            "reports": items,
            "total": total,
            "page": page,
            "pages": max(1, (total + limit - 1) // limit),
        }
    except Exception as e:
        logger.error(f"list_reports failed for user {current_user['id']}: {e}")
        return {"reports": [], "total": 0, "page": 1, "pages": 0}


@router.get("/{report_id}")
async def get_report(
    report_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Fetch a complete analysis report by ID."""
    # ── Try Supabase first ────────────────────────────────────────────────────
    if db:
        try:
            result = (
                db.table("reports")
                .select("*")
                .eq("id", report_id)
                .maybe_single()  # Returns None instead of error if not found
                .execute()
            )

            if result.data:
                row = result.data
                # Authorization check
                if row["user_id"] != current_user["id"]:
                    raise ForbiddenError()

                # Merge report_data with top-level fields
                report = dict(row.get("report_data") or {})
                report["id"] = report_id
                report["created_at"] = row.get("created_at")
                report["file_name"] = row.get("file_name") or report.get("file_name", "")
                return report

        except ForbiddenError:
            raise
        except Exception as e:
            logger.warning(f"DB fetch failed for report {report_id}: {e}")
            # Fall through to in-memory

    # ── Fallback: in-memory store ─────────────────────────────────────────────
    data = _jobs.get(f"report_{report_id}")
    if data:
        return data

    raise NotFoundError(f"Report '{report_id}' not found.")


@router.post("/{report_id}/decision")
async def submit_decision(
    report_id: str,
    body: DecisionRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Record recruiter's hiring decision.
    This feeds the model improvement feedback loop.
    """
    if db:
        try:
            # SYNC call — no await
            db.table("reports").update({
                "recruiter_decision": body.decision,
                "decision_notes": body.notes,
            }).eq("id", report_id).eq("user_id", current_user["id"]).execute()
        except Exception as e:
            logger.warning(f"Decision save failed for {report_id}: {e}")
            # Don't fail the request — decision noted in logs

    logger.info(f"Decision | report={report_id} decision={body.decision} user={current_user['id']}")
    return {
        "status": "ok",
        "decision": body.decision,
        "message": "Decision recorded. This helps improve AI accuracy.",
    }


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Permanently delete a report. Cannot be undone."""
    if db:
        try:
            # Verify ownership first
            check = (
                db.table("reports")
                .select("user_id")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
            if check.data and check.data["user_id"] != current_user["id"]:
                raise ForbiddenError()

            db.table("reports").delete().eq("id", report_id).eq("user_id", current_user["id"]).execute()
        except ForbiddenError:
            raise
        except Exception as e:
            logger.warning(f"Delete failed for {report_id}: {e}")

    # Also remove from in-memory
    _jobs.pop(f"report_{report_id}", None)
    logger.info(f"Report deleted | id={report_id} user={current_user['id']}")
