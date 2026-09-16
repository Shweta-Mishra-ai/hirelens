"""
HireLens — Team Collaboration API
Enhanced with explicit UUID generation & in-memory fallback for demo mode.
"""

import uuid
import time
import logging
from urllib.parse import quote
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, field_validator

from app.core import local_db
from app.services import directory
from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import HireLensException, NotFoundError, ForbiddenError
from app.services.teams.access import (
    get_user_role, can_manage_team, normalize_email as directory_normalize_email,
    _mem_teams, _mem_team_members, _mem_team_invites,
)

logger = logging.getLogger("hirelens")
router = APIRouter()


def _invite_url(email: str, team_id: str) -> str:
    """The link in the invite email.

    The address is percent-encoded. Interpolating it raw breaks plus-addressing
    — `a+team@gmail.com` arrives at the sign-up page as `a team@gmail.com`,
    because a `+` in a query string decodes to a space — and the prefilled
    address then matches no invite.
    """
    from app.core.config import settings
    return (
        f"{settings.FRONTEND_URL}/signup"
        f"?invite_email={quote(email, safe='')}&team_id={quote(team_id, safe='')}"
    )




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

    Without it the team page has only a UUID to render, both as the name and
    as the avatar initials. An id that resolves to nobody is left without a
    name, so the UI can show a neutral badge rather than invent one.
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

    # Every store matches invites on the lowercased address, and so does the
    # acceptance path at signup. Writing whatever spelling the inviter typed
    # means the invitee signs up and joins nothing, with no error on either
    # side. See access.normalize_email().
    invite_email = directory_normalize_email(body.email)
    invite_url = _invite_url(invite_email, team_id)

    if db:
        try:
            team_data = db.table("teams").select("name").eq("id", team_id).maybe_single().execute()
            if team_data and team_data.data:
                team_name = team_data.data.get("name", team_name)

            existing = (
                db.table("team_invites")
                .select("id")
                .eq("team_id", team_id).eq("status", "pending")
                .eq("email", invite_email)
                .execute()
            )
            if existing.data:
                return {"status": "already_invited", "email": invite_email, "invite_url": invite_url}

            db.table("team_invites").insert({
                "id": invite_id,
                "team_id": team_id,
                "email": invite_email,
                "invited_by": current_user["id"],
                "status": "pending",
            }).execute()

            # Attempt Supabase native admin invite email if available
            try:
                if hasattr(db, "auth") and hasattr(db.auth, "admin"):
                    db.auth.admin.invite_user_by_email(invite_email)
            except Exception as e:
                logger.warning(f"Supabase admin invite email skipped: {e}")

        except Exception as e:
            logger.warning(f"DB invite insertion error ({e}) — using in-memory store")

    if team_id in _mem_teams:
        team_name = _mem_teams[team_id].get("name", team_name)

    inviter_name = directory.get_display_name(
        db, current_user["id"], current_user.get("email") or "A recruiter"
    )

    # Send real email via Resend / SMTP
    email_sent = await send_team_invite_email(
        to_email=invite_email,
        team_name=team_name,
        inviter_name=inviter_name,
        invite_url=invite_url,
    )

    # Persist the invite, then mirror it into this process's cache. Without
    # the durable row an invite sent before a restart could never be
    # accepted — the invitee would sign up and silently join nothing.
    local_db.create_invite(invite_id, team_id, invite_email)
    _mem_team_invites.append({
        "id": invite_id,
        "team_id": team_id,
        "email": invite_email,
        "invited_by": current_user["id"],
        "status": "pending",
    })

    return {
        "status": "invited",
        "email": invite_email,
        "email_sent": email_sent,
        "invite_url": invite_url,
    }


@router.get("/{team_id}/invites")
async def list_invites(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    Invites sent for this team that nobody has accepted yet.

    The roster only ever showed people who had already joined, so an invite
    sent to a mistyped address — or one the person simply never acted on —
    was invisible to the owner. They had no way to tell "they haven't joined
    yet" from "I sent it to the wrong address".
    """
    if not get_user_role(db, team_id, current_user["id"]):
        raise ForbiddenError("You are not a member of this team.")

    rows: list[dict] = []
    if db:
        try:
            res = (
                db.table("team_invites")
                .select("id,email,created_at")
                .eq("team_id", team_id)
                .eq("status", "pending")
                .execute()
            )
            rows = res.data or []
        except Exception as e:
            logger.warning(f"DB invite listing failed for team {team_id}: {e}")

    if not rows:
        rows = local_db.list_pending_invites(team_id)

    return {"invites": rows}


@router.delete("/{team_id}/invites/{invite_id}")
async def revoke_invite(
    team_id: str,
    invite_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Withdraw a pending invite — the way to correct a mistyped address."""
    if not can_manage_team(db, team_id, current_user["id"]):
        raise ForbiddenError("Only team owners or admins can withdraw invites.")

    revoked = False
    if db:
        try:
            res = (
                db.table("team_invites")
                .update({"status": "revoked"})
                .eq("id", invite_id)
                .eq("team_id", team_id)
                .execute()
            )
            revoked = bool(res.data)
        except Exception as e:
            logger.warning(f"DB invite revoke failed for {invite_id}: {e}")

    if local_db.revoke_invite(invite_id, team_id):
        revoked = True

    _mem_team_invites[:] = [
        i for i in _mem_team_invites if not (i.get("id") == invite_id and i.get("team_id") == team_id)
    ]

    if not revoked:
        raise NotFoundError("That invite no longer exists, or has already been accepted.")
    return {"status": "revoked"}


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

    # Remove from memory, by MUTATING the list rather than rebinding it.
    #
    # `global _mem_team_members; _mem_team_members = [...]` would only rebind
    # the name inside this module. access.py's get_user_role() reads the
    # original list object through its own binding of that name, so it would
    # never see the change — and removing a member would be a no-op for every
    # authorization check while this process stayed up, with the endpoint
    # still answering {"status": "removed"}.
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
