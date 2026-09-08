"""
HireLens — Team Collaboration API
Enhanced with explicit UUID generation & in-memory fallback for demo mode.
"""

import uuid
import time
import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, field_validator

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
            
            # NOTE: public.team_members has a composite primary key
            # (team_id, user_id) and no `id` column at all (see
            # sql/002_team_collaboration.sql) — this insert used to send an
            # "id" field anyway. PostgREST rejects inserts containing a
            # column that doesn't exist, so every real Supabase insert here
            # was failing and silently falling through to the in-memory
            # fallback below. The practical effect: team creation always
            # *looked* successful, but the membership row (and therefore
            # the team, functionally) never actually persisted to Supabase
            # — it quietly lived in-process memory only, even with a fully
            # configured database.
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

    # In-memory fallback
    team = {"id": team_id, "name": body.name, "owner_id": user_id, "created_at": created_at}
    _mem_teams[team_id] = team
    _mem_team_members.append({"team_id": team_id, "user_id": user_id, "role": "owner", "joined_at": created_at})
    logger.info(f"Team created (in-memory) | id={team_id} owner={user_id} name={body.name}")
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
    user_memberships = [m for m in _mem_team_members if m["user_id"] == user_id]
    teams = []
    for m in user_memberships:
        t = _mem_teams.get(m["team_id"])
        if t:
            t_copy = dict(t)
            t_copy["my_role"] = m["role"]
            teams.append(t_copy)
    return {"teams": teams}


def _resolve_member_identity(db, user_id: str) -> dict:
    """Best-effort display identity for a team member.

    team_members only stores a user_id, so the members list used to render raw
    UUIDs — "da93a615-5821-4b87-a786-2965f4f5e405" as the name of the person
    you are about to give access to your candidate reports. Unusable for the
    one decision the screen exists for: deciding who to remove.

    Resolution is best-effort by design. A member whose identity can't be
    looked up still renders (with a shortened id), because a members list that
    silently drops rows is worse than one with an unresolved entry — you would
    not be able to see, let alone remove, an account you can't name.
    """
    identity = {"email": None, "full_name": None}

    # Supabase Auth is the source of truth when configured.
    if db is not None:
        try:
            admin = getattr(getattr(db, "auth", None), "admin", None)
            if admin is not None:
                res = admin.get_user_by_id(user_id)
                user = getattr(res, "user", None) or res
                email = getattr(user, "email", None)
                meta = getattr(user, "user_metadata", None) or {}
                if email:
                    identity["email"] = email
                    identity["full_name"] = meta.get("full_name") or None
                    return identity
        except Exception as e:
            logger.debug(f"Could not resolve member {user_id} via Supabase Auth: {e}")

    # Local SQLite / in-memory fallbacks.
    try:
        from app.core import local_db

        local_user = local_db.get_user_by_id(user_id)
        if local_user:
            identity["email"] = local_user.get("email")
            identity["full_name"] = local_user.get("full_name") or None
            return identity
    except Exception as e:
        logger.debug(f"Could not resolve member {user_id} locally: {e}")

    try:
        from app.api.v1.endpoints.auth import _mem_users

        for email, u in _mem_users.items():
            if u.get("id") == user_id:
                identity["email"] = email
                identity["full_name"] = u.get("full_name") or None
                return identity
    except Exception:
        pass

    return identity


@router.get("/{team_id}/members")
async def list_team_members(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    role = get_user_role(db, team_id, current_user["id"])
    if not role:
        raise ForbiddenError("You are not a member of this team.")

    rows = None
    if db:
        try:
            res = db.table("team_members").select("user_id,role,joined_at").eq("team_id", team_id).execute()
            if res.data:
                rows = res.data
        except Exception as e:
            logger.warning(f"DB list members failed ({e}) — using in-memory fallback")

    if rows is None:
        rows = [m for m in _mem_team_members if m["team_id"] == team_id]

    members = []
    for row in rows:
        member = dict(row)
        member.update(_resolve_member_identity(db, member.get("user_id", "")))
        member["is_you"] = member.get("user_id") == current_user["id"]
        members.append(member)

    return {"members": members}


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
    inviter_name = current_user.get("full_name") or current_user.get("email") or "A recruiter"

    # Send real email via Resend / SMTP
    email_sent = await send_team_invite_email(
        to_email=str(body.email),
        team_name=team_name,
        inviter_name=inviter_name,
        invite_url=invite_url,
    )

    # In-memory store mirror
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
            db.table("teams").delete().eq("id", team_id).execute()
        except Exception as e:
            logger.warning(f"DB delete team failed: {e}")

    _mem_teams.pop(team_id, None)
    # Same in-place-mutation fix as remove_member() above — see that
    # comment for the full explanation of why `global` + reassignment
    # silently did nothing here.
    _mem_team_members[:] = [m for m in _mem_team_members if m["team_id"] != team_id]
    return {"status": "deleted"}
