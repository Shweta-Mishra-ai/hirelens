"""
HireLens — Plans and usage.

GET  /billing/usage              this account's plan, quota and usage this month
GET  /billing/admin/accounts     operator: newest accounts, or those matching ?q=
GET  /billing/admin/account      operator: one account (?email=), with this month's usage
POST /billing/admin/plan         operator: move an account to a plan

GET  /billing/plans              what can be bought in the app, and the UPI details
POST /billing/payments           "I paid": a UPI transaction reference for a plan
GET  /billing/payments           this account's payment claims
GET  /billing/admin/payments     operator: claims (?status=pending by default)
POST /billing/admin/payments/{id}/approve | /reject   operator: decide a claim

Payment collection is deliberately outside this module. Until a payment
provider is wired to a webhook, an operator records an upgrade here after a
customer pays (any provider, invoice or bank transfer). The quota takes
effect on the customer's next upload.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field

from app.api.v1.endpoints.analysis import _jobs
from app.core import local_db
from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis, require_admin
from app.core.rate_limit import check_rate_limit
from app.core.exceptions import DatabaseUnavailable, NotFoundError
from app.services import billing, payments
from app.services.teams.access import normalize_email

logger = logging.getLogger("hirelens")
router = APIRouter()


@router.get("/usage")
def get_usage(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    return billing.usage_summary(db, current_user["id"], _jobs)


class SetPlanRequest(BaseModel):
    email: EmailStr
    plan: Literal["free", "pro", "team"]


_ACCOUNT_FIELDS = "id,email,full_name,company,created_at"


def _account_for_email(db, email: str) -> dict | None:
    """
    The account with this email, or None. On a Supabase deployment a failed
    lookup is an outage (503), not "no such account": answering 404 would
    tell the operator a paying customer does not exist.
    """
    if db:
        try:
            res = db.table("profiles").select(_ACCOUNT_FIELDS).eq("email", email).limit(1).execute()
        except Exception as e:
            logger.warning(f"Profile lookup by email failed: {e}")
            raise DatabaseUnavailable()
        rows = res.data or []
        if rows:
            return dict(rows[0])
    user = local_db.get_user_by_email(email)
    if not user:
        return None
    return {k: user.get(k) for k in ("id", "email", "full_name", "company", "created_at")}


def _user_id_for_email(db, email: str) -> str | None:
    account = _account_for_email(db, email)
    return str(account["id"]) if account else None


def _plans_for(db, user_ids: list[str]) -> dict[str, str]:
    """Plan per user, one query. Missing means free."""
    if not user_ids:
        return {}
    if db:
        try:
            res = db.table("subscriptions").select("user_id,plan").in_("user_id", user_ids).execute()
            return {str(r["user_id"]): r.get("plan") or "free" for r in (res.data or [])}
        except Exception as e:
            logger.warning(f"Plan lookup for the account list failed: {e}")
            raise DatabaseUnavailable()
    plans = {}
    for uid in user_ids:
        sub = local_db.get_subscription(uid)
        if sub:
            plans[uid] = sub.get("plan") or "free"
    return plans


@router.get("/admin/accounts")
def list_accounts(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
):
    """Newest accounts first, or those whose email contains `q`, with their plan."""
    search = (q or "").strip().lower() or None
    if db:
        try:
            query = db.table("profiles").select(_ACCOUNT_FIELDS)
            if search:
                # PostgREST ilike: escape the pattern characters, so a search
                # for "a_b" means that text, not "a" + any char + "b".
                escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                query = query.ilike("email", f"%{escaped}%")
            rows = query.order("created_at", desc=True).limit(limit).execute().data or []
        except Exception as e:
            logger.warning(f"Account list failed: {e}")
            raise DatabaseUnavailable()
    else:
        rows = local_db.list_users(limit, search)
    plans = _plans_for(db, [str(r["id"]) for r in rows])
    return {
        "accounts": [
            {
                "user_id": str(r["id"]),
                "email": r.get("email"),
                "full_name": r.get("full_name") or "",
                "company": r.get("company") or "",
                "created_at": r.get("created_at"),
                "plan": plans.get(str(r["id"]), "free"),
            }
            for r in rows
        ]
    }


@router.get("/admin/account")
def get_account(
    email: EmailStr,
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
):
    """One account with its plan and this month's usage."""
    account = _account_for_email(db, normalize_email(str(email)))
    if not account:
        raise NotFoundError("No account exists for that email address.")
    uid = str(account["id"])
    return {
        "user_id": uid,
        "email": account.get("email"),
        "full_name": account.get("full_name") or "",
        "company": account.get("company") or "",
        "created_at": account.get("created_at"),
        "usage": billing.usage_summary(db, uid, _jobs),
    }


@router.post("/admin/plan")
def set_plan(body: SetPlanRequest, admin: dict = Depends(require_admin), db=Depends(get_db)):
    email = normalize_email(str(body.email))
    user_id = _user_id_for_email(db, email)
    if not user_id:
        raise NotFoundError("No account exists for that email address.")
    billing.set_plan(db, user_id, body.plan)
    logger.info(f"Plan changed | user={user_id} plan={body.plan} by={admin.get('email')}")
    return {"status": "ok", "user_id": user_id, "plan": body.plan}


# ── UPI payments (see app/services/payments.py) ─────────────────────────────

@router.get("/plans")
def get_plans(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """What the Upgrade page shows: the plans for sale, the UPI details, and
    where this account stands."""
    offers = billing.purchasable_plans()
    return {
        # Only when something can be bought: a UPI ID with no prices set
        # would invite payments the operator has no plan to match.
        "upi_id": (settings.PAYMENT_UPI_ID.strip() or None) if offers else None,
        "payee_name": settings.PAYMENT_PAYEE_NAME.strip() or None,
        "period_days": max(1, int(settings.PLAN_PERIOD_DAYS)),
        "plans": offers,
        "usage": billing.usage_summary(db, current_user["id"], _jobs),
    }


class PaymentClaim(BaseModel):
    plan: Literal["pro", "team"]
    reference: str = Field(..., min_length=1, max_length=64)


@router.post("/payments", status_code=201)
def submit_payment(
    body: PaymentClaim,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    redis=Depends(get_redis),
):
    # Generous for a person, tight for a script guessing references.
    check_rate_limit(redis, f"payment_claim:{current_user['id']}", 10, window_seconds=3600)
    return payments.submit(db, current_user["id"], body.plan, body.reference)


@router.get("/payments")
def my_payments(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    return {"payments": payments.list_mine(db, current_user["id"])}


@router.get("/admin/payments")
def operator_payments(
    status: Literal["pending", "approved", "rejected", "all"] = "pending",
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
):
    return {"payments": payments.list_for_operator(db, None if status == "all" else status)}


@router.post("/admin/payments/{request_id}/approve")
def approve_payment(request_id: str, admin: dict = Depends(require_admin), db=Depends(get_db)):
    return payments.approve(db, request_id, admin.get("email") or "")


class RejectBody(BaseModel):
    note: str | None = Field(default=None, max_length=300)


@router.post("/admin/payments/{request_id}/reject")
def reject_payment(
    request_id: str,
    body: RejectBody | None = None,
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
):
    return payments.reject(db, request_id, admin.get("email") or "", body.note if body else None)
