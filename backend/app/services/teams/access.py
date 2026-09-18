"""
HireLens — Team Access Control
Supports DB & in-memory fallback.
"""

import logging

from app.core import local_db

logger = logging.getLogger("hirelens")

# A per-process cache, not the source of truth. Without Supabase the durable
# answer comes from local_db — a team that lives only in this dict vanishes on
# the next restart, taking its membership with it and leaving any report
# already shared to it pointing at a team_id that no longer resolves.
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


def normalize_email(email: str) -> str:
    """The one spelling of an address used for matching.

    An address is case-insensitive in practice, and every store here keeps it
    lowercased, so a lookup has to lowercase too. Getting this wrong is silent:
    the invitee signs up, joins nothing, and neither they nor the person who
    invited them sees an error.
    """
    return str(email or "").strip().lower()


def accept_pending_invites_for_email(db, user_id: str, email: str) -> int:
    """Auto-accept pending invites by email."""
    accepted = 0
    normalized = normalize_email(email)
    if db:
        try:
            # Every invite row holds the lowercased address: the API writes
            # it that way, and sql/004 both backfilled the existing rows and
            # installed a trigger so nothing can write another spelling.
            pending = (
                db.table("team_invites")
                .select("id,team_id")
                .eq("email", normalized)
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
    accepted += local_db.accept_invites_for_email(normalized, user_id)

    # This process's cache, kept in step so a lookup in the same request
    # doesn't have to hit disk again.
    for inv in _mem_team_invites:
        if normalize_email(inv.get("email")) == normalized and inv["status"] == "pending":
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
