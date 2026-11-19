"""
Deleting an account, on the account holder's own request.

Privacy law (India's DPDP Act, the GDPR) gives people the right to have
their personal data erased, and the privacy policy promises it. Until now
that meant an email to the operator and manual work in the Supabase
dashboard — which failed outright for anyone who had sent a team invite,
until 008 fixed the foreign key.

What is removed: the sign-in account and, through the database's foreign
keys (sql/001-008), the profile, every report and the comments and votes on
it, the person's comments and votes elsewhere, teams they own (for every
member), memberships, plan, usage and session records. Saved job
descriptions have no foreign key, so they are deleted explicitly, first.
The local store and this process's job cache are cleared too.

What stays: one row in deleted_accounts (sql/009) holding the account's
random id and the time — no email, no name. It is what refuses the
account's still-unexpired session tokens; without it they would keep
working for up to seven days.

Order matters, and is chosen so that a failure part-way never locks someone
out of an account that still has their data in it:

1. Refuse while an analysis is running — it would write a report back for an
   account that no longer exists.
2. Check deleted_accounts is reachable, before anything is removed. If 009
   has not been run, nothing is touched and the caller is told so.
3. Saved job descriptions.
4. The auth user (the cascade does the rest).
5. The tombstone. If this one write fails after the account is gone, the
   data is still gone and the old tokens can neither read it nor write (the
   foreign keys refuse a row for a user that does not exist); it is logged
   CRITICAL for the operator.
"""

import logging

from app.core import local_db
from app.core.exceptions import ConflictError, DatabaseUnavailable, StorageWriteFailed
from app.services import sessions

logger = logging.getLogger("hirelens")


class AccountDeletionUnavailable(DatabaseUnavailable):
    code = "account_deletion_unavailable"
    message = (
        "Account deletion isn't available on this server yet. Nothing has been "
        "deleted. Please contact support."
    )


def _is_missing_user(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "")
    status = getattr(exc, "status", None)
    return code == "user_not_found" or status == 404 or "not found" in str(exc).lower()


def _forget_jobs(user_id: str, jobs) -> int:
    """Drop this user's reports and finished jobs from the in-process cache."""
    if jobs is None:
        return 0
    removed = 0
    for key in list(jobs):
        item = jobs.get(key)
        if isinstance(item, dict) and str(item.get("user_id") or "") == user_id:
            jobs.pop(key, None)
            removed += 1
    return removed


def delete_account(db, user_id: str, jobs=None) -> None:
    """Delete everything this account owns. Raises on any failure before the
    account itself is gone, so the caller can report it and nothing is lost."""
    from app.services.billing import in_flight

    running = in_flight(user_id, jobs) if jobs is not None else 0
    if running:
        raise ConflictError(
            f"{running} analysis{'es are' if running != 1 else ' is'} still running. "
            "Wait for it to finish, then delete your account."
        )

    if db is not None:
        # 2. The tombstone table must exist before anything is removed.
        try:
            db.table("deleted_accounts").select("user_id").limit(0).execute()
        except Exception as e:
            logger.error(f"Account deletion refused for {user_id}: deleted_accounts unreachable: {e}")
            raise AccountDeletionUnavailable()

        # 3. No foreign key to auth.users, so not part of the cascade.
        try:
            db.table("saved_jds").delete().eq("user_id", user_id).execute()
        except Exception as e:
            logger.error(f"Account deletion stopped for {user_id}: saved_jds: {e}")
            raise StorageWriteFailed("Your account could not be deleted. Nothing was removed — please try again.")

        # 4. The account; the foreign keys remove the rest.
        try:
            db.auth.admin.delete_user(user_id)
        except Exception as e:
            if not _is_missing_user(e):
                logger.error(f"Account deletion stopped for {user_id}: auth delete failed: {e}")
                raise StorageWriteFailed(
                    "Your account could not be deleted. Your saved job descriptions were "
                    "removed; everything else is unchanged. Please try again."
                )
            logger.info(f"Account {user_id} was already absent from Supabase Auth")

        # 5. Refuse the account's remaining tokens.
        try:
            db.table("deleted_accounts").upsert({"user_id": user_id}, on_conflict="user_id").execute()
        except Exception as e:
            logger.critical(
                f"Account {user_id} was deleted but its tombstone was not written: {e}. "
                "Its unexpired tokens cannot read or write data, but are not refused outright."
            )

    # The local store holds fallback copies even on a Supabase deployment.
    try:
        local_db.delete_user_data(user_id)
    except local_db.LocalStoreError:
        if db is None:
            raise StorageWriteFailed("Your account could not be deleted. Nothing was removed — please try again.")
        logger.error(f"Local copies for deleted account {user_id} could not be removed")

    sessions.mark_deleted(user_id)
    removed = _forget_jobs(user_id, jobs)
    logger.info(f"Account deleted | user={user_id} cached_items={removed}")
