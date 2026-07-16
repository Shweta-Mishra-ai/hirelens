"""
HireLens — Reports API
Fixed:
- All Supabase calls are SYNC (no await)
- Proper error handling on each DB call
- ForbiddenError not swallowed
- Decision validation with proper 422
"""

import re
import logging
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Literal

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError, ForbiddenError
from app.api.v1.endpoints.analysis import _jobs  # in-memory fallback store

logger = logging.getLogger("hirelens")
router = APIRouter()


class DecisionRequest(BaseModel):
    decision: Literal["advance", "schedule_followup", "reject"]
    notes: str | None = None


SEARCH_UNSAFE_CHARS = re.compile(r"[^a-zA-Z0-9 ._+#@\-]")


def _sanitize_search(raw: str) -> str:
    """
    Strict ALLOWLIST (not denylist) for search terms that get embedded into
    a hand-built PostgREST `.or_()` filter string. PostgREST's filter
    mini-language treats comma, parentheses, and other punctuation as
    syntax — an unsanitized search term could inject extra filter
    conditions. Keeping only characters a legitimate name/skill search
    would ever need (letters, digits, spaces, and a few common symbols
    like . + # @ - for things like "C++", "C#", "Node.js") closes that off
    far more reliably than trying to blocklist "the bad ones".
    """
    return SEARCH_UNSAFE_CHARS.sub("", raw).strip()[:100]


SORT_MAP = {
    "newest":     ("created_at", True),
    "oldest":     ("created_at", False),
    "score_desc": ("overall_score", True),
    "score_asc":  ("overall_score", False),
    "name_asc":   ("candidate_name", False),
}


def _mem_reports_for_user(user_id: str) -> list[dict]:
    out = []
    for key, v in _jobs.items():
        if not (key.startswith("report_") and isinstance(v, dict)):
            continue
        # In-memory job dicts don't carry user_id directly on the report blob
        # in older entries — best-effort match, skip if we truly can't tell.
        if v.get("user_id") not in (None, user_id):
            continue
        cred = v.get("credibility") or {}
        cand = v.get("candidate") or {}
        out.append({
            "id": key.replace("report_", "", 1),
            "file_name": v.get("file_name"),
            "candidate_name": cand.get("name") or "Unknown",
            "overall_score": cred.get("overall", 0),
            "recommendation": cred.get("recommendation", "manual_review"),
            "created_at": v.get("created_at") or "",
            "recruiter_decision": v.get("recruiter_decision"),
            "_skills_text": " ".join(
                (v.get("skills") or {}).get("all_claimed") or []
            ).lower(),
        })
    return out


@router.get("")
async def list_reports(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    recommendation: str | None = Query(None),
    search: str | None = Query(None, description="Matches candidate name, file name, or skills"),
    sort: str = Query("newest", description="newest|oldest|score_desc|score_asc|name_asc"),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """List all reports for current recruiter — searchable + sortable."""
    sort_col, sort_desc = SORT_MAP.get(sort, SORT_MAP["newest"])

    if not db:
        items = _mem_reports_for_user(current_user["id"])
        if recommendation and recommendation in ("recommended", "manual_review", "high_risk"):
            items = [r for r in items if r["recommendation"] == recommendation]
        if search:
            s = search.strip().lower()
            items = [
                r for r in items
                if s in (r.get("candidate_name") or "").lower()
                or s in (r.get("file_name") or "").lower()
                or s in r.get("_skills_text", "")
            ]
        for r in items:
            r.pop("_skills_text", None)
        items.sort(key=lambda r: (r.get(sort_col) or ""), reverse=sort_desc)

        total = len(items)
        offset = (page - 1) * limit
        page_items = items[offset: offset + limit]
        return {"reports": page_items, "total": total, "page": page, "pages": max(1, (total + limit - 1) // limit)}

    try:
        offset = (page - 1) * limit

        query = (
            db.table("reports")
            .select("id,file_name,candidate_name,overall_score,recommendation,created_at,recruiter_decision")
            .eq("user_id", current_user["id"])
        )

        if recommendation and recommendation in ("recommended", "manual_review", "high_risk"):
            query = query.eq("recommendation", recommendation)

        if search:
            s = _sanitize_search(search)
            or_filter = (
                f"candidate_name.ilike.%{s}%,"
                f"file_name.ilike.%{s}%,"
                f"report_data->skills->>all_claimed.ilike.%{s}%"
            )
            try:
                query = query.or_(or_filter)
            except Exception as e:
                logger.warning(f"Skill-path search unsupported, falling back to name/file only: {e}")
                query = query.or_(f"candidate_name.ilike.%{s}%,file_name.ilike.%{s}%")

        query = query.order(sort_col, desc=sort_desc).range(offset, offset + limit - 1)

        # SYNC call — no await
        result = query.execute()
        items = result.data or []

        # Count total (respecting the same filters, without range)
        count_query = db.table("reports").select("id", count="exact").eq("user_id", current_user["id"])
        if recommendation and recommendation in ("recommended", "manual_review", "high_risk"):
            count_query = count_query.eq("recommendation", recommendation)
        if search:
            s = _sanitize_search(search)
            try:
                count_query = count_query.or_(
                    f"candidate_name.ilike.%{s}%,file_name.ilike.%{s}%,report_data->skills->>all_claimed.ilike.%{s}%"
                )
            except Exception:
                count_query = count_query.or_(f"candidate_name.ilike.%{s}%,file_name.ilike.%{s}%")
        count_result = count_query.execute()
        total = count_result.count if count_result.count is not None else len(items)

        return {
            "reports": items,
            "total": total,
            "page": page,
            "pages": max(1, (total + limit - 1) // limit),
        }
    except Exception as e:
        logger.error(f"list_reports failed for user {current_user['id']}: {e}")
        return {"reports": [], "total": 0, "page": 1, "pages": 0}


@router.get("/export.csv")
async def export_all_reports_csv(
    recommendation: str | None = Query(None),
    search: str | None = Query(None),
    sort: str = Query("newest"),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Exports every report matching the current filters/search/sort as CSV (cap 1000 rows)."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    sort_col, sort_desc = SORT_MAP.get(sort, SORT_MAP["newest"])
    CAP = 1000

    if not db:
        items = _mem_reports_for_user(current_user["id"])
        if recommendation and recommendation in ("recommended", "manual_review", "high_risk"):
            items = [r for r in items if r["recommendation"] == recommendation]
        if search:
            s = search.strip().lower()
            items = [
                r for r in items
                if s in (r.get("candidate_name") or "").lower()
                or s in (r.get("file_name") or "").lower()
                or s in r.get("_skills_text", "")
            ]
        for r in items:
            r.pop("_skills_text", None)
        items.sort(key=lambda r: (r.get(sort_col) or ""), reverse=sort_desc)
        items = items[:CAP]
    else:
        try:
            query = (
                db.table("reports")
                .select("id,file_name,candidate_name,overall_score,recommendation,created_at,recruiter_decision")
                .eq("user_id", current_user["id"])
            )
            if recommendation and recommendation in ("recommended", "manual_review", "high_risk"):
                query = query.eq("recommendation", recommendation)
            if search:
                s = _sanitize_search(search)
                try:
                    query = query.or_(
                        f"candidate_name.ilike.%{s}%,file_name.ilike.%{s}%,report_data->skills->>all_claimed.ilike.%{s}%"
                    )
                except Exception:
                    query = query.or_(f"candidate_name.ilike.%{s}%,file_name.ilike.%{s}%")
            result = query.order(sort_col, desc=sort_desc).limit(CAP).execute()
            items = result.data or []
        except Exception as e:
            logger.error(f"export_all_reports_csv failed for user {current_user['id']}: {e}")
            items = []

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Candidate Name", "File Name", "Score", "Recommendation", "Recruiter Decision", "Created At", "Report ID"])
    for r in items:
        writer.writerow([
            r.get("candidate_name") or "Unknown", r.get("file_name") or "", r.get("overall_score") or 0,
            r.get("recommendation") or "", r.get("recruiter_decision") or "", r.get("created_at") or "", r.get("id") or "",
        ])
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="hirelens_all_reports.csv"'},
    )


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
