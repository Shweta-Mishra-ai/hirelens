"""
HireLens — Team Collaboration API
Enhanced with explicit UUID generation & in-memory fallback for demo mode.
"""

import uuid
import time
import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, field_validator

from app.core import local_db
from app.services import directory
from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import HireLensException, NotFoundError, ForbiddenError
from app.services.teams.access import (
    get_user_role, can_manage_team,
    _mem_teams, _mem_team_members, _mem_team_invites,
)

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


@router.post("")
async def create_team(body: CreateTeamRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    team_id = str(uuid.uuid4())
    user_id = current_user["id"]
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if db:
        try:
            team_res = db.table("teams").insert({
                "id": team_id,
                "name": body.name,
                "owner_id": user_id,
            }).execute()
            team = team_res.data[0] if team_res.data else {"id": team_id, "name": body.name, "owner_id": user_id}
            
            # No "id" here: team_members is keyed on (team_id, user_id) and
            # has no id column, so PostgREST rejected the whole insert. The
            # except below swallowed it, which left the team row in Supabase
            # with its owner holding no membership — and on a deployment
            # whose local disk is ephemeral, the owner lost access to their
            # own team on the next restart while invitees kept theirs.
            db.table("team_members").insert({
                "team_id": team_id,
                "user_id": user_id,
                "role": "owner",
            }).execute()
            
            # Mirror to in-memory
            _mem_teams[team_id] = team
            _mem_team_members.append({"team_id": team_id, "user_id": user_id, "role": "owner", "joined_at": created_at})
            return team
        except Exception as e:
            logger.warning(f"DB Team creation failed ({e}) — using in-memory fallback")

    # Local fallback — persisted, then mirrored into this process's cache.
    team = {"id": team_id, "name": body.name, "owner_id": user_id, "created_at": created_at,
            "my_role": "owner"}
    local_db.create_team(team_id, body.name, user_id, created_at)
    _mem_teams[team_id] = team
    _mem_team_members.append({"team_id": team_id, "user_id": user_id, "role": "owner", "joined_at": created_at})
    logger.info(f"Team created | id={team_id} owner={user_id} name={body.name}")
    return team


@router.get("")
async def list_my_teams(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    user_id = current_user["id"]
    if db:
        try:
            memberships = db.table("team_members").select("team_id,role").eq("user_id", user_id).execute()
            team_ids = [m["team_id"] for m in (memberships.data or [])]
            if team_ids:
                roles_by_team = {m["team_id"]: m["role"] for m in memberships.data}
                teams_res = db.table("teams").select("*").in_("id", team_ids).execute()
                teams = teams_res.data or []
                for t in teams:
                    t["my_role"] = roles_by_team.get(t["id"])
                return {"teams": teams}
        except Exception as e:
            logger.warning(f"DB list teams failed ({e}) — using in-memory fallback")

    # In-memory fallback
    # Durable rows first, then anything this process knows that has not been
    # persisted, de-duplicated by team id.
    by_id: dict[str, dict] = {t["id"]: t for t in local_db.list_teams_for_user(user_id)}

    for m in (mm for mm in _mem_team_members if mm["user_id"] == user_id):
        cached = _mem_teams.get(m["team_id"])
        if cached and m["team_id"] not in by_id:
            by_id[m["team_id"]] = {**cached, "my_role": m["role"]}

    return {"teams": list(by_id.values())}


def _with_member_names(rows: list[dict], current_user_id: str, db=None) -> list[dict]:
    """
    Add `user_name` so the member list shows people, not user ids.

    The team page previously rendered the raw UUID as the member's name and
    built their avatar initials from it. The names are already in the users
    table; nothing was reading them. Unresolvable ids are left without a
    name so the UI can show a neutral badge instead of inventing one.
    """
    if not rows:
        return rows

    names = directory.get_display_names(db, [r.get("user_id") for r in rows])
    out = []
    for row in rows:
        enriched = dict(row)
        uid = row.get("user_id")
        if uid == current_user_id:
            enriched["user_name"] = "You"
            enriched["is_me"] = True
        else:
            profile = names.get(uid) or {}
            display = (profile.get("full_name") or "").strip() or (profile.get("email") or "").strip()
            if display:
                enriched["user_name"] = display
            enriched["is_me"] = False
        out.append(enriched)
    return out


@router.get("/{team_id}/members")
async def list_team_members(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    role = get_user_role(db, team_id, current_user["id"])
    if not role:
        raise ForbiddenError("You are not a member of this team.")

    if db:
        try:
            res = db.table("team_members").select("user_id,role,joined_at").eq("team_id", team_id).execute()
            if res.data:
                return {"members": _with_member_names(res.data, current_user["id"], db)}
        except Exception as e:
            logger.warning(f"DB list members failed ({e}) — using in-memory fallback")

    members = local_db.list_team_members(team_id)
    if not members:
        members = [m for m in _mem_team_members if m["team_id"] == team_id]
    return {"members": _with_member_names(members, current_user["id"], db)}


@router.post("/{team_id}/invite")
async def invite_member(team_id: str, body: InviteRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    if not can_manage_team(db, team_id, current_user["id"]):
        raise ForbiddenError("Only team owners or admins can send invites.")

    from app.core.config import settings
    from app.services.email.sender import send_team_invite_email

    invite_id = str(uuid.uuid4())
    team_name = "HireLens Workspace"

    if db:
        try:
            team_data = db.table("teams").select("name").eq("id", team_id).maybe_single().execute()
            if team_data and team_data.data:
                team_name = team_data.data.get("name", team_name)

            existing = (
                db.table("team_invites")
                .select("id")
                .eq("team_id", team_id).eq("email", body.email).eq("status", "pending")
                .execute()
            )
            if existing.data:
                invite_url = f"{settings.FRONTEND_URL}/signup?invite_email={body.email}&team_id={team_id}"
                return {"status": "already_invited", "email": body.email, "invite_url": invite_url}

            db.table("team_invites").insert({
                "id": invite_id,
                "team_id": team_id,
                "email": body.email,
                "invited_by": current_user["id"],
                "status": "pending",
            }).execute()

            # Attempt Supabase native admin invite email if available
            try:
                if hasattr(db, "auth") and hasattr(db.auth, "admin"):
                    db.auth.admin.invite_user_by_email(str(body.email))
            except Exception as e:
                logger.warning(f"Supabase admin invite email skipped: {e}")

        except Exception as e:
            logger.warning(f"DB invite insertion error ({e}) — using in-memory store")

    if team_id in _mem_teams:
        team_name = _mem_teams[team_id].get("name", team_name)

    invite_url = f"{settings.FRONTEND_URL}/signup?invite_email={body.email}&team_id={team_id}"
    inviter_name = directory.get_display_name(
        db, current_user["id"], current_user.get("email") or "A recruiter"
    )

    # Send real email via Resend / SMTP
    email_sent = await send_team_invite_email(
        to_email=str(body.email),
        team_name=team_name,
        inviter_name=inviter_name,
        invite_url=invite_url,
    )

    # Persist the invite, then mirror it into this process's cache. Without
    # the durable row an invite sent before a restart could never be
    # accepted — the invitee would sign up and silently join nothing.
    local_db.create_invite(invite_id, team_id, str(body.email))
    _mem_team_invites.append({
        "id": invite_id,
        "team_id": team_id,
        "email": body.email,
        "invited_by": current_user["id"],
        "status": "pending",
    })

    return {
        "status": "invited",
        "email": body.email,
        "email_sent": email_sent,
        "invite_url": invite_url,
    }


@router.delete("/{team_id}/members/{user_id}")
async def remove_member(team_id: str, user_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    if not can_manage_team(db, team_id, current_user["id"]):
        raise ForbiddenError()

    target_role = get_user_role(db, team_id, user_id)
    if target_role == "owner":
        raise HireLensException("Cannot remove the team owner.")

    if db:
        try:
            db.table("team_members").delete().eq("team_id", team_id).eq("user_id", user_id).execute()
        except Exception as e:
            logger.warning(f"DB remove member failed: {e}")

    # Remove from memory.
    #
    # This used to do `global _mem_team_members; _mem_team_members = [...]`,
    # which only rebinds the NAME `_mem_team_members` inside this module
    # (teams.py). It does not touch the list object that access.py's
    # get_user_role() actually reads — that's a separate binding of the
    # same original name, imported at the top of this file. The practical
    # effect: removing a team member was a complete no-op for every
    # authorization check for as long as the process stayed up, even
    # though this endpoint returned {"status": "removed"}.
    #
    # Mutating the list in place (slice assignment) instead of rebinding
    # the name means every module holding a reference to this list — this
    # one and access.py — sees the same change, because it's still the
    # same object.
    local_db.remove_team_member(team_id, user_id)
    _mem_team_members[:] = [
        m for m in _mem_team_members
        if not (m["team_id"] == team_id and m["user_id"] == user_id)
    ]
    return {"status": "removed"}


@router.delete("/{team_id}")
async def delete_team(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    if get_user_role(db, team_id, current_user["id"]) != "owner":
        raise ForbiddenError()

    if db:
        try:
            # Membership and outstanding invites go with the team. Leaving
            # the rows behind would keep every ex-member passing
            # is_team_member() for this id — and any report still stamped
            # with it readable to them.
            db.table("team_members").delete().eq("team_id", team_id).execute()
            db.table("team_invites").delete().eq("team_id", team_id).execute()
            db.table("teams").delete().eq("id", team_id).execute()
        except Exception as e:
            logger.warning(f"DB delete team failed: {e}")

    # Durable rows too — without this the team was still on disk and came
    # back, roster intact, on the next restart.
    local_db.delete_team(team_id, current_user["id"])
    _mem_teams.pop(team_id, None)
    # Same in-place-mutation fix as remove_member() above — see that
    # comment for the full explanation of why `global` + reassignment
    # silently did nothing here.
    _mem_team_members[:] = [m for m in _mem_team_members if m["team_id"] != team_id]
    return {"status": "deleted"}
