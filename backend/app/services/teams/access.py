"""
HireLens — Team Access Control

A report is visible to: its owner, OR any member of the team it's been
shared with (report.team_id set). This module centralizes that check so
reports.py, and the comments/votes endpoints all apply the exact same rule
— duplicating an authorization check across files is how access-control
bugs happen.

DB-only feature: teams don't have a meaningful in-memory fallback (a team
that vanishes on restart isn't a team), so these helpers return "no access"
gracefully when no DB is configured rather than pretending team membership
exists.
"""

import logging

logger = logging.getLogger("hirelens")


def get_user_role(db, team_id: str, user_id: str) -> str | None:
    """Returns 'owner' | 'admin' | 'member' | None (not a member)."""
    if not db:
        return None
    try:
        res = (
            db.table("team_members")
            .select("role")
            .eq("team_id", team_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return res.data["role"] if res.data else None
    except Exception as e:
        logger.warning(f"Team role lookup failed for team={team_id} user={user_id}: {e}")
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
    """
    Called on every login/signup: joins the user to any team they have a
    pending invite for, matched by email. This is what makes the invite flow
    work without needing to send/track invite emails ourselves — the
    invited person just needs to log in with the email they were invited at.
    Returns the number of invites accepted (0 is normal/expected most of the time).
    """
    if not db:
        return 0
    try:
        pending = (
            db.table("team_invites")
            .select("id,team_id")
            .eq("email", email)
            .eq("status", "pending")
            .execute()
        )
        invites = pending.data or []
        if not invites:
            return 0

        accepted = 0
        for invite in invites:
            try:
                db.table("team_members").upsert({
                    "team_id": invite["team_id"], "user_id": user_id, "role": "member",
                }, on_conflict="team_id,user_id").execute()
                db.table("team_invites").update({"status": "accepted"}).eq("id", invite["id"]).execute()
                accepted += 1
            except Exception as e:
                logger.warning(f"Failed to accept invite {invite['id']} for {email}: {e}")
        return accepted
    except Exception as e:
        logger.warning(f"Invite lookup failed for {email}: {e}")
        return 0
