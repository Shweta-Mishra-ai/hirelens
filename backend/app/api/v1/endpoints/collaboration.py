"""
HireLens — Report Collaboration API (comments, votes, sharing with a team)

A report stays owned by whoever ran the analysis — sharing just makes it
visible to teammates (report.team_id set), it doesn't transfer ownership.
Every endpoint here re-checks access via app.services.teams.access on each
call rather than trusting a cached permission, since team membership can
change between requests.
"""

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from typing import Literal

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import HireLensException, NotFoundError, ForbiddenError, DBRequiredError
from app.api.v1.endpoints.analysis import _jobs
from app.core import local_db
from app.services.teams.access import user_can_access_report, is_team_member

logger = logging.getLogger("hirelens")
router = APIRouter()


class ShareRequest(BaseModel):
    team_id: str


class CommentRequest(BaseModel):
    comment: str

    @field_validator("comment")
    @classmethod
    def not_blank(cls, v):
        v = v.strip()
        if not v or len(v) > 2000:
            raise ValueError("Comment must be 1-2000 characters.")
        return v


class VoteRequest(BaseModel):
    vote: Literal["advance", "reject", "maybe"]


def _fetch_report_row(db, report_id: str) -> dict:
    """
    The report row, from Supabase when configured and the local store
    otherwise.

    This used to raise DBRequiredError the moment `db` was falsy, which took
    the entire Discuss tab — comments, votes and sharing — out of service on
    any deployment without Supabase. The feature is documented as working, so
    failing the whole tab with a 503 rather than degrading was a bug, not a
    deliberate limitation.
    """
    if db:
        try:
            res = (
                db.table("reports")
                .select("id,user_id,team_id,candidate_name")
                .eq("id", report_id)
                .maybe_single()
                .execute()
            )
        except Exception as e:
            logger.error(f"Report lookup failed for {report_id}: {e}")
            raise HireLensException("Could not look up this report.")
        if not res.data:
            raise NotFoundError(f"Report '{report_id}' not found.")
        return res.data

    # Local path. `team_id` is None because team sharing needs Supabase —
    # see share_report below, which says so explicitly rather than failing.
    mem = _jobs.get(f"report_{report_id}")
    if mem is not None and mem.get("_owner_user_id"):
        return {
            "id": report_id,
            "user_id": mem["_owner_user_id"],
            "team_id": None,
            "candidate_name": (mem.get("candidate") or {}).get("name") or "Unknown",
        }

    for row in local_db.list_reports_any_owner(report_id):
        return {
            "id": report_id,
            "user_id": row["user_id"],
            "team_id": None,
            "candidate_name": row.get("candidate_name") or "Unknown",
        }

    raise NotFoundError(f"Report '{report_id}' not found.")


def _local_mode(db) -> bool:
    """True when there is no Supabase and the SQLite fallback is in play."""
    return not db


@router.post("/{report_id}/share")
async def share_report(report_id: str, body: ShareRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """Owner-only: shares a report with a team they belong to."""
    if _local_mode(db):
        # Team membership itself lives in Supabase, so there is no correct
        # local answer here. Name the reason instead of a bare 503.
        raise DBRequiredError(
            "Sharing a report with a team needs the shared database, which "
            "isn't configured on this deployment. Comments and votes still "
            "work on reports you own."
        )
    row = _fetch_report_row(db, report_id)
    if row["user_id"] != current_user["id"]:
        raise ForbiddenError()
    if not is_team_member(db, body.team_id, current_user["id"]):
        raise HireLensException("You must be a member of the team you're sharing with.")

    try:
        db.table("reports").update({"team_id": body.team_id}).eq("id", report_id).execute()
        return {"status": "shared", "team_id": body.team_id}
    except Exception as e:
        logger.error(f"Share report failed for {report_id}: {e}")
        raise HireLensException("Could not share this report. Please try again.")


@router.post("/{report_id}/unshare")
async def unshare_report(report_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    if _local_mode(db):
        raise DBRequiredError(
            "Team sharing isn't configured on this deployment."
        )
    row = _fetch_report_row(db, report_id)
    if row["user_id"] != current_user["id"]:
        raise ForbiddenError()
    try:
        db.table("reports").update({"team_id": None}).eq("id", report_id).execute()
        return {"status": "unshared"}
    except Exception as e:
        logger.error(f"Unshare report failed for {report_id}: {e}")
        raise HireLensException("Could not unshare this report. Please try again.")


@router.get("/{report_id}/comments")
async def list_comments(report_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    row = _fetch_report_row(db, report_id)
    if not user_can_access_report(db, row, current_user["id"]):
        raise ForbiddenError()
    if _local_mode(db):
        return {"comments": local_db.list_comments(report_id)}

    try:
        res = db.table("report_comments").select("*").eq("report_id", report_id).order("created_at").execute()
        return {"comments": res.data or []}
    except Exception as e:
        logger.error(f"List comments failed for {report_id}: {e}")
        return {"comments": []}


@router.post("/{report_id}/comments")
async def add_comment(report_id: str, body: CommentRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    row = _fetch_report_row(db, report_id)
    if not user_can_access_report(db, row, current_user["id"]):
        raise ForbiddenError()
    if _local_mode(db):
        created = local_db.add_comment(report_id, current_user["id"], body.comment)
        if not created:
            raise HireLensException("Could not post comment. Please try again.")
        return created

    try:
        res = db.table("report_comments").insert({
            "report_id": report_id, "user_id": current_user["id"], "comment": body.comment,
        }).execute()
        return res.data[0]
    except Exception as e:
        logger.error(f"Add comment failed for {report_id}: {e}")
        raise HireLensException("Could not post comment. Please try again.")


@router.delete("/{report_id}/comments/{comment_id}")
async def delete_comment(report_id: str, comment_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    if _local_mode(db):
        # Author-only deletion is enforced inside the query.
        if not local_db.delete_comment(comment_id, current_user["id"]):
            raise NotFoundError("Comment not found, or it isn't yours to delete.")
        return {"status": "deleted"}

    try:
        res = db.table("report_comments").select("user_id").eq("id", comment_id).eq("report_id", report_id).maybe_single().execute()
    except Exception as e:
        logger.error(f"Comment lookup failed for {comment_id}: {e}")
        raise HireLensException("Could not look up this comment.")
    if not res.data:
        raise NotFoundError("Comment not found.")
    if res.data["user_id"] != current_user["id"]:
        raise ForbiddenError()
    try:
        db.table("report_comments").delete().eq("id", comment_id).execute()
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Delete comment failed for {comment_id}: {e}")
        raise HireLensException("Could not delete comment. Please try again.")


@router.get("/{report_id}/votes")
async def list_votes(report_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    row = _fetch_report_row(db, report_id)
    if not user_can_access_report(db, row, current_user["id"]):
        raise ForbiddenError()
    if _local_mode(db):
        votes = local_db.list_votes(report_id)
    else:
        try:
            res = db.table("report_votes").select("*").eq("report_id", report_id).execute()
            votes = res.data or []
        except Exception as e:
            logger.error(f"List votes failed for {report_id}: {e}")
            votes = []

    tally = {"advance": 0, "reject": 0, "maybe": 0}
    for v in votes:
        if v.get("vote") in tally:
            tally[v["vote"]] += 1

    my_vote = next((v["vote"] for v in votes if v["user_id"] == current_user["id"]), None)
    return {"votes": votes, "tally": tally, "my_vote": my_vote}


@router.post("/{report_id}/vote")
async def cast_vote(report_id: str, body: VoteRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    row = _fetch_report_row(db, report_id)
    if not user_can_access_report(db, row, current_user["id"]):
        raise ForbiddenError()
    if _local_mode(db):
        if not local_db.cast_vote(report_id, current_user["id"], body.vote):
            raise HireLensException("Could not record your vote. Please try again.")
        return {"status": "voted", "vote": body.vote}

    try:
        # upsert on (report_id, user_id) — one vote per person, casting again updates it
        db.table("report_votes").upsert({
            "report_id": report_id, "user_id": current_user["id"], "vote": body.vote,
        }, on_conflict="report_id,user_id").execute()
        return {"status": "voted", "vote": body.vote}
    except Exception as e:
        logger.error(f"Cast vote failed for {report_id}: {e}")
        raise HireLensException("Could not record your vote. Please try again.")
