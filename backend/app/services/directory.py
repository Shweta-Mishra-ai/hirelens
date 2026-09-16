"""
Turning a user id into a person.

Comment threads, team rosters and the signature on candidate emails all need
a name. Where those names live depends on how the instance is deployed:

  * With Supabase, users are in `auth.users`, which PostgREST does not
    expose. `public.profiles` mirrors the readable fields (see
    backend/sql/001_core_schema.sql, which creates it, keeps it in step with
    a trigger, and backfills anyone who signed up earlier).
  * Without Supabase, they are rows in the local SQLite `users` table.

Every caller used to read the SQLite table directly. On a Supabase
deployment that table has no rows at all, so the fix that stopped raw UUIDs
appearing in the UI never actually applied to the deployment that runs in
production: teammates showed as a neutral badge and every candidate email
went out signed with the recruiter's raw email address instead of their
name. This module asks Supabase first and falls back to SQLite, so one
lookup is right on both.
"""

import logging

from app.core import local_db

logger = logging.getLogger("hirelens")


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def get_display_names(db, user_ids) -> dict[str, dict]:
    """
    Map user ids to `{"full_name": ..., "email": ...}`.

    Ids that cannot be resolved are simply absent from the result; callers
    are expected to show a neutral label rather than printing the id.
    """
    ids = [str(u) for u in dict.fromkeys(user_ids) if u]
    if not ids:
        return {}

    resolved: dict[str, dict] = {}

    if db:
        try:
            res = db.table("profiles").select("id,full_name,email").in_("id", ids).execute()
            for row in res.data or []:
                uid = str(row.get("id") or "")
                if not uid:
                    continue
                resolved[uid] = {
                    "full_name": _clean(row.get("full_name")),
                    "email": _clean(row.get("email")),
                }
        except Exception as e:
            # An instance whose profiles table predates 001, or a transient
            # failure. A missing name is a neutral badge, never an error page.
            logger.warning(f"Profile name lookup failed, falling back to the local store: {e}")

    missing = [uid for uid in ids if not (resolved.get(uid) or {}).get("full_name")]
    if missing:
        for uid, profile in local_db.get_display_names(missing).items():
            existing = resolved.get(uid) or {}
            resolved[uid] = {
                "full_name": _clean(profile.get("full_name")) or existing.get("full_name", ""),
                "email": _clean(profile.get("email")) or existing.get("email", ""),
            }

    return {uid: p for uid, p in resolved.items() if p.get("full_name") or p.get("email")}


def get_display_name(db, user_id: str, fallback: str = "") -> str:
    """One person's name for the top of an email, with a fallback."""
    if not user_id:
        return fallback
    profile = get_display_names(db, [user_id]).get(str(user_id)) or {}
    return profile.get("full_name") or fallback
