"""
HireLens — Team Collaboration API
Enhanced with explicit UUID generation & in-memory fallback for demo mode.
"""

import uuid
import time
import logging
from starlette.concurrency import run_in_threadpool
from urllib.parse import quote
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, field_validator

from app.core import local_db
from app.services import directory
from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import (
    HireLensException, NotFoundError, ForbiddenError, StorageWriteFailed, DatabaseUnavailable,
)
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
def create_team(body: CreateTeamRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
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
            # With Supabase configured it is the only store teammates and
            # invites are read from. Falling back to the local file put the
            # team on a disk Render wipes at every restart: it worked until
            # then and vanished with no error, as the invite path below
            # already refuses to do.
            logger.error(f"Team create failed in Supabase | id={team_id} owner={user_id}: {e}")
            try:
                db.table("teams").delete().eq("id", team_id).execute()
            except Exception:
                pass  # the insert may not have happened at all
            raise StorageWriteFailed("That team could not be saved. Please try again.")

    # Local fallback — persisted, then mirrored into this process's cache.
    #
    # The durable write is checked. This is the only store on this deployment,
    # so ignoring a failure would hand back a team id for a team that exists
    # only in this process — working until the next restart, then gone, with
    # no error ever shown and every report shared to it left dangling.
    team = {"id": team_id, "name": body.name, "owner_id": user_id, "created_at": created_at,
            "my_role": "owner"}
    if not local_db.create_team(team_id, body.name, user_id, created_at):
        logger.error(f"Team create failed to persist | id={team_id} owner={user_id}")
        raise StorageWriteFailed("That team could not be saved. Please try again.")
    _mem_teams[team_id] = team
    _mem_team_members.append({"team_id": team_id, "user_id": user_id, "role": "owner", "joined_at": created_at})
    logger.info(f"Team created | id={team_id} owner={user_id} name={body.name}")
    return team


@router.get("")
def list_my_teams(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
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
            return {"teams": []}
        except Exception as e:
            # An empty list here reads as "you have no teams" during an outage.
            logger.warning(f"DB list teams failed for {user_id}: {e}")
            raise DatabaseUnavailable()

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
def list_team_members(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    role = get_user_role(db, team_id, current_user["id"])
    if not role:
        raise ForbiddenError("You are not a member of this team.")

    if db:
        try:
            res = db.table("team_members").select("user_id,role,joined_at").eq("team_id", team_id).execute()
            return {"members": _with_member_names(res.data or [], current_user["id"], db)}
        except Exception as e:
            logger.warning(f"DB list members failed for {team_id}: {e}")
            raise DatabaseUnavailable()

    members = local_db.list_team_members(team_id)
    if not members:
        members = [m for m in _mem_team_members if m["team_id"] == team_id]
    return {"members": _with_member_names(members, current_user["id"], db)}


_TEAM_REPORT_FIELDS = (
    "id,user_id,file_name,candidate_name,overall_score,recommendation,"
    "recruiter_decision,created_at"
)


@router.get("/{team_id}/reports")
def list_team_reports(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    The candidate files shared with this team, newest first. Members only.

    Without this a teammate had no way to find a shared report: the
    dashboard lists your own uploads, and the team page listed people only —
    so "share with a team" worked only if the owner also sent the link.
    """
    if not get_user_role(db, team_id, current_user["id"]):
        raise ForbiddenError("You are not a member of this team.")

    if db:
        try:
            rows = (
                db.table("reports").select(_TEAM_REPORT_FIELDS)
                .eq("team_id", team_id).order("created_at", desc=True).limit(100)
                .execute().data
            ) or []
        except Exception as e:
            # An empty list here would read as "nothing shared yet".
            logger.warning(f"Team reports lookup failed for {team_id}: {e}")
            raise DatabaseUnavailable()
    else:
        try:
            rows = local_db.list_team_reports(team_id, limit=100)
        except local_db.LocalStoreError:
            raise DatabaseUnavailable()

    owners = _with_member_names(
        [{"user_id": r.get("user_id")} for r in rows], current_user["id"], db
    )
    reports = []
    for row, owner in zip(rows, owners):
        reports.append({
            "id": row.get("id"),
            "candidate_name": row.get("candidate_name") or "Unknown",
            "file_name": row.get("file_name") or "",
            "overall_score": row.get("overall_score"),
            "recommendation": row.get("recommendation"),
            "recruiter_decision": row.get("recruiter_decision"),
            "created_at": row.get("created_at"),
            "shared_by": owner.get("user_name"),
            "is_mine": bool(owner.get("is_me")),
        })
    return {"reports": reports}


@router.post("/{team_id}/invite")
async def invite_member(team_id: str, body: InviteRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    from app.services.email.sender import send_team_invite_email

    # Every store matches invites on the lowercased address, and so does the
    # acceptance path at signup. Writing whatever spelling the inviter typed
    # means the invitee signs up and joins nothing, with no error on either
    # side. See access.normalize_email().
    invite_email = directory_normalize_email(body.email)
    invite_url = _invite_url(invite_email, team_id)
    invite_id = str(uuid.uuid4())

    def persist() -> dict:
        """
        Everything synchronous, on a worker thread: the permission check, the
        team name, the duplicate check and the durable write.

        The write happens BEFORE any email goes out. The old order sent the
        email first and persisted second, so a failed write raised "has not
        been sent" for an invitation that was already in the invitee's inbox
        — and could never be accepted.
        """
        if not can_manage_team(db, team_id, current_user["id"]):
            raise ForbiddenError("Only team owners or admins can send invites.")

        team_name = "HireLens Workspace"
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
                    return {"already": True}

                db.table("team_invites").insert({
                    "id": invite_id,
                    "team_id": team_id,
                    "email": invite_email,
                    "invited_by": current_user["id"],
                    "status": "pending",
                }).execute()
            except Exception as e:
                # With Supabase configured it is the store the signup path
                # reads. An invite kept only in the local fallback lives on an
                # ephemeral disk and is lost at the next restart.
                logger.error(f"Invite insert failed | team={team_id}: {e}")
                raise StorageWriteFailed(
                    "That invitation could not be saved, so it has not been sent. Please try again."
                )
            # Deliberately NOT calling db.auth.admin.invite_user_by_email. It
            # creates a password-less account for the address and sends a
            # second email whose link this app does not handle, after which
            # the invitee's own sign-up can collide with that account. The
            # app's invite link below is the one designed flow.

        if team_id in _mem_teams:
            team_name = _mem_teams[team_id].get("name", team_name)

        if not local_db.create_invite(invite_id, team_id, invite_email) and not db:
            # Without Supabase this row is the invite.
            logger.error(f"Invite failed to persist | team={team_id}")
            raise StorageWriteFailed(
                "That invitation could not be saved, so it has not been sent. Please try again."
            )
        _mem_team_invites.append({
            "id": invite_id,
            "team_id": team_id,
            "email": invite_email,
            "invited_by": current_user["id"],
            "status": "pending",
        })

        inviter_name = directory.get_display_name(
            db, current_user["id"], current_user.get("email") or "A recruiter"
        )
        return {"already": False, "team_name": team_name, "inviter_name": inviter_name}

    outcome = await run_in_threadpool(persist)
    if outcome["already"]:
        return {"status": "already_invited", "email": invite_email, "invite_url": invite_url}

    email_sent = await send_team_invite_email(
        to_email=invite_email,
        team_name=outcome["team_name"],
        inviter_name=outcome["inviter_name"],
        invite_url=invite_url,
    )

    return {
        "status": "invited",
        "email": invite_email,
        "email_sent": email_sent,
        "invite_url": invite_url,
    }


@router.get("/{team_id}/invites")
def list_invites(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
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
def revoke_invite(
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
def remove_member(team_id: str, user_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
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
    # A failed delete here is not "nothing to remove" — it means this person
    # still has access while the response says otherwise. Revocation reports
    # what actually happened.
    try:
        local_db.remove_team_member(team_id, user_id)
    except local_db.LocalStoreError:
        logger.error(f"Member removal failed to persist | team={team_id} user={user_id}")
        raise StorageWriteFailed(
            "That member could not be removed. Their access is unchanged — please try again."
        )

    _mem_team_members[:] = [
        m for m in _mem_team_members
        if not (m["team_id"] == team_id and m["user_id"] == user_id)
    ]
    return {"status": "removed"}


@router.delete("/{team_id}")
def delete_team(team_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
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
            # Carrying on reported "deleted" for a team still in Supabase,
            # roster and shared reports intact.
            logger.error(f"DB delete team failed for {team_id}: {e}")
            raise StorageWriteFailed(
                "That team could not be deleted. Please try again."
            )

    # Durable rows too — without this the team was still on disk and came
    # back, roster intact, on the next restart.
    try:
        local_db.delete_team(team_id, current_user["id"])
    except local_db.LocalStoreError:
        logger.error(f"Team deletion failed to persist | team={team_id}")
        raise StorageWriteFailed(
            "That team could not be deleted. Nothing has changed — please try again."
        )
    _mem_teams.pop(team_id, None)
    # Same in-place-mutation fix as remove_member() above — see that
    # comment for the full explanation of why `global` + reassignment
    # silently did nothing here.
    _mem_team_members[:] = [m for m in _mem_team_members if m["team_id"] != team_id]
    return {"status": "deleted"}
