"""
Plans and monthly usage quotas.

What is metered: completed analyses — one per resume that produced a report,
whichever path it came through (single upload, bulk, JD match, ATS import).
An analysis that fails is never counted, so a parser error or a provider
outage costs the customer nothing.

Where usage lives: an append-only ledger (`usage_events`, sql/007), never a
count of `reports`. Users can delete reports, and counting them would hand
quota back for every deletion.

When it is checked: at upload, before anything is queued, against
    used this month + this user's analyses still in flight + the new files.
Counting in-flight work closes the gap where a user starts several batches
before any of them has finished and been recorded.

Quotas are configuration (see config.py). A limit of 0 means unlimited, and
every plan defaults to 0, so deploying this changes nothing until the
operator sets limits.
"""

import logging
from datetime import datetime, timezone

from app.core import local_db
from app.core.config import settings
from app.core.exceptions import QuotaExceeded

logger = logging.getLogger("hirelens")

PLANS = ("free", "pro", "team")


def monthly_limit(plan: str) -> int:
    """Analyses per calendar month on `plan`; 0 means unlimited."""
    return {
        "free": settings.FREE_MONTHLY_ANALYSES,
        "pro": settings.PRO_MONTHLY_ANALYSES,
        "team": settings.TEAM_MONTHLY_ANALYSES,
    }.get(plan, settings.FREE_MONTHLY_ANALYSES)


def period_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Start of this calendar month and of the next, in UTC."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _plan_from_row(row: dict | None) -> tuple[str, datetime | None]:
    """(plan, expiry) for a subscription row. A plan bought for a period
    (current_period_end) is free again once that moment has passed; one set
    by an operator with no end date does not expire."""
    if not row or row.get("status") not in (None, "active") or row.get("plan") not in PLANS:
        return "free", None
    ends = _parse_time(row.get("current_period_end"))
    if ends and ends <= datetime.now(timezone.utc):
        return "free", None
    return row["plan"], ends


def get_subscription(db, user_id: str) -> tuple[str, datetime | None]:
    """The user's plan and when it lapses (None: it does not). Anything
    unreadable or inactive is treated as free."""
    if db:
        try:
            res = (
                db.table("subscriptions")
                .select("plan,status,current_period_end")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            row = res.data if res else None
            if row:
                return _plan_from_row(row)
            return "free", None
        except Exception as e:
            # Not raised: a plan lookup failure must not lock a paying
            # customer out. They are metered as free for this request, which
            # with default limits is unlimited.
            logger.warning(f"Plan lookup failed for {user_id}, treating as free: {e}")
    return _plan_from_row(local_db.get_subscription(user_id))


def get_plan(db, user_id: str) -> str:
    """The user's plan. Anything unreadable, inactive or lapsed is free."""
    return get_subscription(db, user_id)[0]


def purchasable_plans() -> list[dict]:
    """Plans that can be bought in the app: priced above 0, with UPI set up."""
    if not settings.PAYMENT_UPI_ID.strip():
        return []
    prices = {"pro": settings.PRO_PRICE_INR, "team": settings.TEAM_PRICE_INR}
    return [
        {"plan": plan, "price_inr": int(price), "monthly_analyses": monthly_limit(plan) or None}
        for plan, price in prices.items()
        if int(price or 0) > 0
    ]


def upgrade_link() -> str | None:
    """Where "Upgrade" goes: the operator's own link if set, else the in-app
    UPI page when something can be bought there, else nowhere."""
    if settings.UPGRADE_URL:
        return settings.UPGRADE_URL
    return "/upgrade" if purchasable_plans() else None


def used_this_period(db, user_id: str) -> int:
    start, _ = period_bounds()
    since = start.isoformat()
    if db:
        try:
            res = (
                db.table("usage_events")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("kind", "analysis")
                .gte("created_at", since)
                .limit(1)
                .execute()
            )
            return int(res.count or 0)
        except Exception as e:
            logger.warning(f"Usage count failed for {user_id}: {e}")
    return local_db.count_usage_since(user_id, since)


def record_analysis(db, user_id: str, report_id: str | None) -> None:
    """
    Append one completed analysis to the ledger. Never raises: the report
    already exists and the customer must get it. A failure is logged at
    ERROR, because it is revenue the meter did not see.
    """
    if db:
        try:
            db.table("usage_events").insert({
                "user_id": user_id,
                "kind": "analysis",
                "report_id": report_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            return
        except Exception as e:
            logger.error(f"Usage event not recorded in Supabase for {user_id}: {e}")
    if not local_db.record_usage(user_id, "analysis", report_id):
        logger.error(f"Usage event not recorded anywhere for {user_id} (report {report_id})")


def in_flight(user_id: str, jobs) -> int:
    """This user's analyses accepted but not yet finished, in this process."""
    count = 0
    for key in list(jobs):
        if key.startswith("report_"):
            continue
        job = jobs.get(key)
        if isinstance(job, dict) and job.get("user_id") == user_id and job.get("status") in ("queued", "running"):
            count += 1
    return count


def usage_summary(db, user_id: str, jobs=None) -> dict:
    plan, plan_ends = get_subscription(db, user_id)
    limit = monthly_limit(plan)
    used = used_this_period(db, user_id)
    pending = in_flight(user_id, jobs) if jobs is not None else 0
    start, end = period_bounds()
    return {
        "plan": plan,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "used": used,
        "in_progress": pending,
        "limit": limit or None,
        "remaining": None if not limit else max(0, limit - used - pending),
        "unlimited": not limit,
        "upgrade_url": upgrade_link(),
        # When a plan bought for a period lapses back to free; null if never.
        "plan_expires_at": plan_ends.isoformat() if plan_ends else None,
    }


def ensure_quota(db, user_id: str, requested: int, jobs) -> None:
    """Raise QuotaExceeded unless `requested` more analyses fit this month."""
    plan = get_plan(db, user_id)
    limit = monthly_limit(plan)
    if not limit:
        return
    used = used_this_period(db, user_id)
    pending = in_flight(user_id, jobs)
    remaining = max(0, limit - used - pending)
    if requested > remaining:
        if remaining == 0:
            detail = f"You've used all {limit} analyses included in your {plan} plan this month."
        else:
            detail = (
                f"That's {requested} resumes, and your {plan} plan has {remaining} "
                f"analys{'is' if remaining == 1 else 'es'} left this month."
            )
        raise QuotaExceeded(detail, plan=plan, limit=limit, remaining=remaining)


def set_plan(
    db,
    user_id: str,
    plan: str,
    period_end: datetime | None = None,
    provider: str | None = None,
    reference: str | None = None,
) -> None:
    """
    Move an account to `plan`. With `period_end`, the plan lapses back to
    free at that moment (a paid month); without, it does not expire (an
    operator's manual change). Raises if nothing stored it.
    """
    from app.core.exceptions import StorageWriteFailed

    if plan not in PLANS:
        raise ValueError(f"Unknown plan {plan!r}")
    ends = period_end.isoformat() if period_end else None
    if db:
        try:
            db.table("subscriptions").upsert({
                "user_id": user_id,
                "plan": plan,
                "status": "active",
                "current_period_end": ends,
                "provider": provider,
                "provider_reference": reference,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="user_id").execute()
            return
        except Exception as e:
            logger.error(f"Plan change failed in Supabase for {user_id}: {e}")
            raise StorageWriteFailed("The plan could not be changed. Nothing was modified.")
    if not local_db.set_subscription(user_id, plan, current_period_end=ends):
        raise StorageWriteFailed("The plan could not be changed. Nothing was modified.")
