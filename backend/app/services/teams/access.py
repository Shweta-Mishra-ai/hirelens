"""
HireLens — Team Access Control
Supports DB & in-memory fallback.
"""

import logging

from app.core import local_db

logger = logging.getLogger("hirelens")

# These remain as a per-process cache so existing imports and tests keep
# working, but they are no longer the source of truth: without Supabase the
# durable answer comes from local_db. They used to BE the store, which is why
# a team created on a deployment without Supabase vanished on the next
# restart, taking its membership with it and leaving any report already
# shared to that team pointing at a team_id that no longer resolved.
_mem_teams: dict[str, dict] = {}
_mem_team_members: list[dict] = []
_mem_team_invites: list[dict] = []


def get_user_role(db, team_id: str, user_id: str) -> str | None:
    """Returns 'owner' | 'admin' | 'member' | None (not a member)."""
    if db:
        try:
            res = (
                db.table("team_members")
                .select("role")
                .eq("team_id", team_id)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if res.data:
                return res.data["role"]
        except Exception as e:
            logger.warning(f"Team role lookup failed for team={team_id} user={user_id}: {e}")

    # Durable local store, then this process's cache.
    role = local_db.get_team_role(team_id, user_id)
    if role:
        return role

    for m in _mem_team_members:
        if m["team_id"] == team_id and m["user_id"] == user_id:
            return m["role"]
    return None


def is_team_member(db, team_id: str, user_id: str) -> bool:
    return get_user_role(db, team_id, user_id) is not None


def can_manage_team(db, team_id: str, user_id: str) -> bool:
    """Owner or admin — can invite/remove members."""
    return get_user_role(db, team_id, user_id) in ("owner", "admin")


def user_can_access_report(db, report_row: dict, user_id: str) -> bool:
    """report_row must include at least 'user_id' and 'team_id'."""
    if report_row.get("user_id") == user_id:
        return True
    team_id = report_row.get("team_id")
    if team_id and is_team_member(db, team_id, user_id):
        return True
    return False


def accept_pending_invites_for_email(db, user_id: str, email: str) -> int:
    """Auto-accept pending invites by email."""
    accepted = 0
    if db:
        try:
            pending = (
                db.table("team_invites")
                .select("id,team_id")
                .eq("email", email)
                .eq("status", "pending")
                .execute()
            )
            invites = pending.data or []
            for invite in invites:
                try:
                    db.table("team_members").upsert({
                        "team_id": invite["team_id"], "user_id": user_id, "role": "member",
                    }, on_conflict="team_id,user_id").execute()
                    db.table("team_invites").update({"status": "accepted"}).eq("id", invite["id"]).execute()
                    accepted += 1
                except Exception as e:
                    logger.warning(f"Failed to accept invite {invite['id']} for {email}: {e}")
        except Exception as e:
            logger.warning(f"Invite lookup failed for {email}: {e}")

    # Durable local invites.
    accepted += local_db.accept_invites_for_email(email, user_id)

    # This process's cache, kept in step so a lookup in the same request
    # doesn't have to hit disk again.
    for inv in _mem_team_invites:
        if inv["email"] == email and inv["status"] == "pending":
            inv["status"] = "accepted"
            already = any(
                m["team_id"] == inv["team_id"] and m["user_id"] == user_id
                for m in _mem_team_members
            )
            if not already:
                _mem_team_members.append(
                    {"team_id": inv["team_id"], "user_id": user_id, "role": "member"}
                )

    return accepted
