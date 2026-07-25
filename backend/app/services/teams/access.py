"""
HireLens — Team Access Control
Supports DB & in-memory fallback.
"""

import logging

logger = logging.getLogger("hirelens")

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

    # Fallback in-memory check
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

    # In-memory invites auto-accept
    for inv in _mem_team_invites:
        if inv["email"] == email and inv["status"] == "pending":
            inv["status"] = "accepted"
            _mem_team_members.append({"team_id": inv["team_id"], "user_id": user_id, "role": "member"})
            accepted += 1

    return accepted
