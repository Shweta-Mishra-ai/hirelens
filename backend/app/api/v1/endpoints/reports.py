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
from pydantic import BaseModel, Field, field_validator
from typing import Literal

from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.exceptions import NotFoundError, ForbiddenError, HireLensException, ValidationError
from app.core.rate_limit import check_rate_limit
from app.core.config import settings
from app.core import local_db
from app.api.v1.endpoints.analysis import _jobs  # in-memory fallback store
from app.services.teams.access import user_can_access_report

logger = logging.getLogger("hirelens")
router = APIRouter()


class DecisionRequest(BaseModel):
    decision: Literal["advance", "schedule_followup", "reject"]
    notes: str | None = None


class NotifyRequest(BaseModel):
    decision: Literal["advance", "schedule_followup", "reject"]
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=10_000)

    @field_validator("subject", "body")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("cannot be blank or whitespace-only")
        return v


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


def _local_reports_for_user(user_id: str) -> list[dict]:
    """
    Every report we can see for this user without Supabase: the durable
    SQLite rows, plus anything this process analysed that has not been
    persisted (a storage failure, or a report written by an older build).

    SQLite is the primary source here — `_jobs` is a process-local dict that
    empties on restart, so relying on it alone is what made reports vanish
    after a Render sleep.
    """
    by_id: dict[str, dict] = {}

    for row in local_db.list_reports(user_id):
        by_id[row["id"]] = {
            "id": row["id"],
            "file_name": row.get("file_name") or "",
            "candidate_name": row.get("candidate_name") or "Unknown",
            "overall_score": row.get("overall_score") or 0,
            "recommendation": row.get("recommendation") or "manual_review",
            "created_at": row.get("created_at") or "",
            "recruiter_decision": row.get("recruiter_decision"),
            # Skill text is only used for search; the summary row doesn't
            # carry it, so in-memory entries below can enrich it.
            "_skills_text": "",
        }

    for mem in _mem_reports_for_user(user_id):
        existing = by_id.get(mem["id"])
        if existing is None:
            by_id[mem["id"]] = mem
        elif mem.get("_skills_text"):
            existing["_skills_text"] = mem["_skills_text"]

    return list(by_id.values())


def _mem_reports_for_user(user_id: str) -> list[dict]:
    out = []
    for key, v in _jobs.items():
        if not (key.startswith("report_") and isinstance(v, dict)):
            continue
        # Reports are stamped with `_owner_user_id` at write time (see
        # analysis.py's _run_analysis and verify.py's _persist_verification).
        # This used to check the wrong key (`user_id`, which report blobs
        # never actually had) and treated a missing owner as "visible to
        # everyone" — which meant, in practice, that this endpoint returned
        # every user's reports to every user whenever the DB path wasn't
        # taken. Fail closed: no owner stamp means nobody sees it here.
        if v.get("_owner_user_id") != user_id:
            continue
        cred = v.get("credibility") or {}
        cand = v.get("candidate") or {}
        out.append({
            "id": key.replace("report_", "", 1),
            # `_owner_file_name` is the legacy key — report blobs written by
            # earlier versions only carry that one. See analysis.py's
            # _stamp_report_metadata().
            "file_name": v.get("file_name") or v.get("_owner_file_name") or "",
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
        items = _local_reports_for_user(current_user["id"])
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
            # NOTE: .or_() only builds the filter — it makes no network call,
            # so it can't itself raise a PostgREST error. The previous
            # try/except here was dead code; any actual failure (e.g. an
            # unsupported JSON-path filter) only surfaces from .execute()
            # below, which is now wrapped separately so search failures are
            # distinguishable from "no results" instead of silently
            # returning an empty list either way.
            query = query.or_(
                f"candidate_name.ilike.%{s}%,"
                f"file_name.ilike.%{s}%,"
                f"report_data->skills->>all_claimed.ilike.%{s}%"
            )

        query = query.order(sort_col, desc=sort_desc).range(offset, offset + limit - 1)

        try:
            # SYNC call — no await
            result = query.execute()
        except Exception as e:
            if search:
                logger.warning(f"Skill-path search query failed, retrying name/file only: {e}")
                fallback_query = (
                    db.table("reports")
                    .select("id,file_name,candidate_name,overall_score,recommendation,created_at,recruiter_decision")
                    .eq("user_id", current_user["id"])
                )
                if recommendation and recommendation in ("recommended", "manual_review", "high_risk"):
                    fallback_query = fallback_query.eq("recommendation", recommendation)
                s = _sanitize_search(search)
                fallback_query = fallback_query.or_(f"candidate_name.ilike.%{s}%,file_name.ilike.%{s}%")
                fallback_query = fallback_query.order(sort_col, desc=sort_desc).range(offset, offset + limit - 1)
                result = fallback_query.execute()  # let this one raise for real if it also fails
            else:
                raise
        items = result.data or []

        # Count total (respecting the same filters, without range)
        count_query = db.table("reports").select("id", count="exact").eq("user_id", current_user["id"])
        if recommendation and recommendation in ("recommended", "manual_review", "high_risk"):
            count_query = count_query.eq("recommendation", recommendation)
        if search:
            s = _sanitize_search(search)
            count_query = count_query.or_(
                f"candidate_name.ilike.%{s}%,file_name.ilike.%{s}%,report_data->skills->>all_claimed.ilike.%{s}%"
            )
        try:
            count_result = count_query.execute()
            total = count_result.count if count_result.count is not None else len(items)
        except Exception as e:
            # The main query above already succeeded (or fell back
            # successfully) — don't fail the whole request just because the
            # separate count query had trouble. Fall back to len(items) as
            # a page-count estimate rather than erroring or lying with 0.
            logger.warning(f"list_reports count query failed, using page length as estimate: {e}")
            total = len(items)

        return {
            "reports": items,
            "total": total,
            "page": page,
            "pages": max(1, (total + limit - 1) // limit),
        }
    except Exception as e:
        # This used to return {"reports": [], "total": 0} — indistinguishable
        # from "you have no reports yet" in the UI. A DB outage should never
        # look identical to a brand-new, empty account; the frontend needs a
        # real error here so it can show "couldn't load, retry" instead of
        # a false empty state.
        logger.error(f"list_reports failed for user {current_user['id']}: {e}")
        raise HireLensException(
            "Could not load your reports right now due to a database error. Please try again."
        )


@router.get("/analytics")
async def get_talent_analytics(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Enterprise Talent Analytics & Workforce Intelligence (Feature C)
    Aggregates candidate pool statistics:
    - Score distribution (Recommended, Manual Review, High Risk)
    - Top skill clusters
    - Risk flag breakdown
    - Average candidate credibility score
    """
    items = []
    if db:
        try:
            res = (
                db.table("reports")
                .select("id,overall_score,recommendation,report_data")
                .eq("user_id", current_user["id"])
                .limit(500)
                .execute()
            )
            items = res.data or []
        except Exception as e:
            logger.warning(f"Analytics DB query warning for {current_user['id']}: {e}")

    if not items:
        # Fallback to in-memory items for user
        items = _local_reports_for_user(current_user["id"])

    total = len(items)
    if total == 0:
        return {
            "total_candidates": 0,
            "avg_credibility_score": 0,
            "distribution": {"recommended": 0, "manual_review": 0, "high_risk": 0},
            "top_skills": [],
            "risk_categories": {},
        }

    scores = [int(i.get("overall_score") or 0) for i in items]
    avg_score = round(sum(scores) / len(scores)) if scores else 0

    dist = {"recommended": 0, "manual_review": 0, "high_risk": 0}
    skill_counts: dict[str, int] = {}
    risk_cats: dict[str, int] = {}

    for i in items:
        rec = i.get("recommendation") or "manual_review"
        dist[rec] = dist.get(rec, 0) + 1

        rdata = i.get("report_data") or i
        sk = (rdata.get("skills") or {}).get("all_claimed") or []
        for s in sk:
            if isinstance(s, str) and s.strip():
                clean_s = s.strip().title()
                skill_counts[clean_s] = skill_counts.get(clean_s, 0) + 1

        fl = rdata.get("flags") or []
        for f in fl:
            if isinstance(f, dict) and f.get("category"):
                cat = f["category"].lower().strip()
                risk_cats[cat] = risk_cats.get(cat, 0) + 1

    top_skills = sorted(
        [{"skill": k, "count": v} for k, v in skill_counts.items()],
        key=lambda x: x["count"],
        reverse=True
    )[:10]

    return {
        "total_candidates": total,
        "avg_credibility_score": avg_score,
        "distribution": dist,
        "top_skills": top_skills,
        "risk_categories": risk_cats,
    }



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
        items = _local_reports_for_user(current_user["id"])
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
    """Fetch a complete analysis report by ID — visible to its owner or any
    member of the team it's been shared with."""
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
                if not user_can_access_report(db, row, current_user["id"]):
                    raise ForbiddenError()

                # Merge report_data with top-level fields
                report = dict(row.get("report_data") or {})
                report["id"] = report_id
                report["created_at"] = row.get("created_at")
                report["file_name"] = row.get("file_name") or report.get("file_name", "")
                report["team_id"] = row.get("team_id")
                return report

        except ForbiddenError:
            raise
        except Exception as e:
            logger.warning(f"DB fetch failed for report {report_id}: {e}")
            # Fall through to in-memory

    # ── Fallback: in-memory store ─────────────────────────────────────────────
    # Same ownership rule as the DB path above: no owner stamp means nobody
    # can read it here, not "everybody can". See _mem_reports_for_user()
    # above for the fuller explanation of why this was previously fail-open.
    data = _jobs.get(f"report_{report_id}")
    if data:
        if data.get("_owner_user_id") != current_user["id"]:
            raise ForbiddenError()
        return data

    # ── Fallback: durable local store ─────────────────────────────────────────
    # Reached after a restart, when the in-memory copy is gone. Ownership is
    # part of the query, so a wrong owner and a missing row are
    # indistinguishable from here.
    persisted = local_db.get_report(report_id, current_user["id"])
    if persisted:
        # Warm this process's cache so repeat reads skip the disk.
        _jobs[f"report_{report_id}"] = persisted
        return persisted

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

    This used to always return {"status": "ok"} — even when the DB write
    raised an exception, and even when the update matched zero rows (wrong
    report_id, or a report belonging to someone else). Both cases told the
    recruiter "recorded" when nothing was saved. It also never wrote
    anything to the in-memory fallback store at all, so a decision made
    while the DB was unavailable was silently discarded every time. Both
    are fixed below: DB errors and zero-row matches now raise a real error,
    and the in-memory path actually persists the decision.
    """
    saved = False

    if db:
        try:
            # SYNC call — no await
            res = (
                db.table("reports")
                .update({
                    "recruiter_decision": body.decision,
                    "decision_notes": body.notes,
                })
                .eq("id", report_id)
                .eq("user_id", current_user["id"])
                .execute()
            )
            if res.data:
                saved = True
            # res.data == [] means either the report doesn't exist or
            # belongs to someone else — either way, not an error to swallow.
        except Exception as e:
            logger.error(f"Decision save failed for {report_id}: {e}")
            raise HireLensException(
                "Could not save your decision due to a database error. Please try again."
            )

    if not saved:
        # Either there's no DB configured, or the DB update matched zero
        # rows. Write to the durable local store first — the in-memory copy
        # below is only a cache for this process, and a decision that exists
        # solely there is lost on the next restart.
        if local_db.set_report_decision(report_id, current_user["id"], body.decision):
            saved = True

        mem_key = f"report_{report_id}"
        existing = _jobs.get(mem_key)
        if existing is not None and existing.get("_owner_user_id") == current_user["id"]:
            existing["recruiter_decision"] = body.decision
            existing["decision_notes"] = body.notes
            saved = True

    if not saved:
        raise NotFoundError(
            f"Report '{report_id}' not found, or you don't have access to it."
        )

    logger.info(f"Decision | report={report_id} decision={body.decision} user={current_user['id']}")
    return {
        "status": "ok",
        "decision": body.decision,
        # No claim about model improvement here: recruiter decisions are
        # stored against the report and are not used for training.
        "message": "Decision recorded on this candidate's file.",
    }


@router.get("/{report_id}/notify/draft")
async def get_notify_draft(
    report_id: str,
    decision: Literal["advance", "schedule_followup", "reject"] = Query(...),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Returns a default {subject, body, candidate_email} for the given decision,
    used to pre-fill the "edit before sending" panel. Never sends anything.
    """
    from app.services.email.sender import build_decision_email

    report = await get_report(report_id, current_user, db)  # reuses access checks + fallback
    candidate = report.get("candidate") or {}
    candidate_email = candidate.get("email")
    candidate_name = candidate.get("name") or "Candidate"

    sender_name = current_user.get("full_name") or current_user.get("email") or "The Hiring Team"
    team_name = "HireLens"
    if db:
        try:
            team_id = report.get("team_id")
            if team_id:
                t = db.table("teams").select("name").eq("id", team_id).maybe_single().execute()
                if t and t.data:
                    team_name = t.data.get("name") or team_name
        except Exception as e:
            logger.warning(f"notify draft team lookup failed: {e}")

    draft = build_decision_email(decision, candidate_name, sender_name, team_name)

    return {
        "candidate_email": candidate_email,
        "candidate_name": candidate_name,
        "subject": draft["subject"],
        "body": draft["body"],
        "has_email": bool(candidate_email),
    }


@router.post("/{report_id}/notify")
async def notify_candidate(
    report_id: str,
    body: NotifyRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Sends the (default or recruiter-edited) decision email to the candidate.
    This is a deliberate, separate step from saving a decision — recording
    a decision never auto-emails anyone; the recruiter always chooses to notify.

    Rate-limited per user: this triggers a real external email send (cost +
    candidate-facing side effect), unlike most read/write endpoints, so a
    double-click or buggy retry loop shouldn't be able to spam a candidate.
    """
    from app.services.email.sender import send_candidate_decision_email

    check_rate_limit(redis, f"notify:{current_user['id']}", settings.NOTIFY_RATE_LIMIT_PER_MINUTE)

    report = await get_report(report_id, current_user, db)
    candidate = report.get("candidate") or {}
    candidate_email = candidate.get("email")

    if not candidate_email:
        raise ValidationError(
            "No email address was found for this candidate. "
            "Add one manually or ask them to resubmit with contact info."
        )

    sent = await send_candidate_decision_email(
        to_email=str(candidate_email),
        subject=body.subject,
        body=body.body,
    )

    if db:
        try:
            db.table("reports").update({
                "candidate_notified_at": "now()",
                "candidate_notified_decision": body.decision,
            }).eq("id", report_id).eq("user_id", current_user["id"]).execute()
        except Exception as e:
            logger.warning(f"Could not record notification timestamp for {report_id}: {e}")

    logger.info(f"Notify | report={report_id} decision={body.decision} email_sent={sent} to={candidate_email}")

    return {
        "status": "sent" if sent else "queued_no_provider",
        "email_sent": sent,
        "candidate_email": candidate_email,
        "message": (
            "Email sent to the candidate."
            if sent else
            "No email provider is configured (RESEND_API_KEY or SMTP), so the message "
            "was not actually delivered. Configure one to send real emails."
        ),
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

    # Also remove from in-memory — but only if this user actually owns it.
    # This used to pop() unconditionally: any authenticated user could
    # delete any other user's in-memory report just by guessing/obtaining
    # its ID, with no ownership check at all.
    mem_key = f"report_{report_id}"
    existing = _jobs.get(mem_key)
    if existing is not None:
        if existing.get("_owner_user_id") != current_user["id"]:
            raise ForbiddenError()
        _jobs.pop(mem_key, None)

    # And from the durable local store, or the report would reappear on the
    # next restart when the in-memory cache is repopulated from disk.
    local_db.delete_report(report_id, current_user["id"])

    logger.info(f"Report deleted | id={report_id} user={current_user['id']}")
