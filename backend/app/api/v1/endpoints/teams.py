"""
HireLens — Team Collaboration API

Lets recruiters share candidate reports with teammates and discuss them
together instead of screening solo. DB-required (Supabase) — a team without
persistence isn't meaningful, so this returns a clear error rather than
silently no-op'ing when no DB is configured.

Invite flow deliberately avoids needing email-sending infrastructure: an
invite is just a (team_id, email) row. The next time ANYONE logs in or signs
up with that email, app/api/v1/endpoints/auth.py auto-accepts any pending
invites for them. The inviter can also just share the team_id/name manually
in the meantime — no external service required, $0 cost.
"""

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, field_validator

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import HireLensException, NotFoundError, ForbiddenError, DBRequiredError
from app.services.teams.access import get_user_role, can_manage_team

logger = logging.getLogger("hirelens")
router = APIRouter()


class CreateTeamRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v):
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("Team name must be 1-100 characters.")
        return v


class InviteRequest(BaseModel):
    email: EmailStr


def _require_db(db):
    if not db:
        raise DBRequiredError()


@router.post("")
async def create_team(body: CreateTeamRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    _require_db(db)
    try:
        team_res = db.table("teams").insert({"name": body.name, "owner_id": current_user["id"]}).execute()
        team = team_res.data[0]
        db.table("team_members").insert({
            "team_id": team["id"], "user_id": current_user["id"], "role": "owner",
        }).execute()
        return team
    except Exception as e:
        logger.error(f"Team creation failed for user {current_user['id']}: {e}")
        raise HireLensException("Could not create team. Please try again.")


@router.get("")
async def list_my_teams(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    _require_db(db)
    try:
        memberships = db.table("team_members").select("team_id,role").eq("user_id", current_user["id"]).execute()
        team_ids = [m["team_id"] for m in (memberships.data or [])]
        if not team_ids:
            return {"teams": []}
        roles_by_team = {m["team_id"]: m["role"] for m in memberships.data}
        teams_res = db.table("teams").select("*").in_("id", team_ids).execute()
        teams = teams_res.data or []
        for t in teams:
            t["my_role"] = roles_by_team.get(t["id"])
        return {"teams": teams}
    except Exception as e:
        logger.error(f"List teams failed for user {current_user['id']}: {e}")
        return {"teams": []}


@router.get("/{team_id}/members")
async def list_team_members(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    _require_db(db)
    if not get_user_role(db, team_id, current_user["id"]):
        raise ForbiddenError()
    try:
        res = db.table("team_members").select("user_id,role,joined_at").eq("team_id", team_id).execute()
        return {"members": res.data or []}
    except Exception as e:
        logger.error(f"List members failed for team {team_id}: {e}")
        return {"members": []}


@router.post("/{team_id}/invite")
async def invite_member(team_id: str, body: InviteRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    _require_db(db)
    if not can_manage_team(db, team_id, current_user["id"]):
        raise ForbiddenError()

    try:
        # Auto-accept immediately if the invited email already has an account
        # and is somehow already checking — otherwise it activates on their
        # next login (see auth.py). Either path, no duplicate pending invites.
        existing = (
            db.table("team_invites")
            .select("id")
            .eq("team_id", team_id).eq("email", body.email).eq("status", "pending")
            .execute()
        )
        if existing.data:
            return {"status": "already_invited"}

        db.table("team_invites").insert({
            "team_id": team_id, "email": body.email, "invited_by": current_user["id"], "status": "pending",
        }).execute()
        return {"status": "invited", "email": body.email}
    except Exception as e:
        logger.error(f"Invite failed for team {team_id}: {e}")
        raise HireLensException("Could not send invite. Please try again.")


@router.delete("/{team_id}/members/{user_id}")
async def remove_member(team_id: str, user_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    _require_db(db)
    if not can_manage_team(db, team_id, current_user["id"]):
        raise ForbiddenError()

    target_role = get_user_role(db, team_id, user_id)
    if target_role == "owner":
        raise HireLensException("Cannot remove the team owner. Transfer ownership first.")

    try:
        db.table("team_members").delete().eq("team_id", team_id).eq("user_id", user_id).execute()
        return {"status": "removed"}
    except Exception as e:
        logger.error(f"Remove member failed for team {team_id}: {e}")
        raise HireLensException("Could not remove member. Please try again.")


@router.delete("/{team_id}")
async def delete_team(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    _require_db(db)
    if get_user_role(db, team_id, current_user["id"]) != "owner":
        raise ForbiddenError()
    try:
        db.table("teams").delete().eq("id", team_id).execute()
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Delete team failed for {team_id}: {e}")
        raise HireLensException("Could not delete team. Please try again.")
