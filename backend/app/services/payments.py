"""
UPI payments, verified by an operator. No payment gateway.

The customer pays the operator's UPI ID from any UPI app — the in-app
Upgrade page shows the ID, the amount and a QR code — and submits the
transaction reference (the 12-digit UTR the app shows). An operator finds
that reference in the bank statement and approves or rejects the claim on
the operator screen. Approval grants the plan for PLAN_PERIOD_DAYS, added to
whatever paid time on the same plan is still left.

Why this and not a gateway: it costs nothing and needs no merchant account,
which is what the business has today. What it does not do: confirm the money
arrived. That is the operator's check, and nothing is granted without it.

Rules, enforced in Postgres (sql/010) and repeated here for clear messages:
a reference can be claimed once (a rejected claim frees it, so a typo can be
fixed), and an account has at most one claim waiting.
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from app.core import local_db
from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    DatabaseUnavailable,
    NotFoundError,
    StorageWriteFailed,
    ValidationError,
)
from app.services import billing

logger = logging.getLogger("hirelens")

# UPI transaction references are 12 digits; bank and wallet references vary,
# so letters and digits, 6-35 long, after removing spaces and dashes.
_REFERENCE = re.compile(r"^[A-Z0-9]{6,35}$")
_PUBLIC_FIELDS = ("id", "plan", "amount_inr", "method", "reference", "status", "note", "created_at", "decided_at")


def normalize_reference(raw: str) -> str:
    ref = re.sub(r"[\s\-]", "", raw or "").upper()
    if not _REFERENCE.match(ref):
        raise ValidationError(
            "Enter the transaction reference your UPI app shows for this payment — "
            "usually a 12-digit UTR number."
        )
    return ref


def _public(row: dict) -> dict:
    return {k: row.get(k) for k in _PUBLIC_FIELDS}


def _is_unique_violation(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "")
    return code == "23505" or "duplicate key" in str(exc).lower()


def submit(db, user_id: str, plan: str, reference: str) -> dict:
    """Record a claim that `user_id` paid for `plan`. Nothing is granted yet."""
    offers = {p["plan"]: p for p in billing.purchasable_plans()}
    if plan not in offers:
        raise ValidationError("That plan can't be bought in the app right now.")
    ref = normalize_reference(reference)
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "plan": plan,
        "amount_inr": offers[plan]["price_inr"],
        "method": "upi",
        "reference": ref,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    waiting = ConflictError(
        "You already have a payment waiting to be verified. You'll see it change here "
        "once it has been checked."
    )
    reused = ConflictError(
        "This transaction reference has already been submitted. Check the number in your UPI app."
    )

    if db:
        try:
            pending = (
                db.table("payment_requests").select("id")
                .eq("user_id", user_id).eq("status", "pending").limit(1).execute().data
            )
            if pending:
                raise waiting
            taken = (
                db.table("payment_requests").select("id")
                .eq("reference", ref).neq("status", "rejected").limit(1).execute().data
            )
            if taken:
                raise reused
            db.table("payment_requests").insert({**row, "status": "pending"}).execute()
        except ConflictError:
            raise
        except Exception as e:
            if _is_unique_violation(e):
                # Lost a race with a second submission; the database said no.
                raise reused if "reference" in str(e).lower() else waiting
            logger.error(f"Payment claim not stored for {user_id}: {e}")
            raise StorageWriteFailed("Your payment details could not be saved. Please try again.")
    else:
        try:
            local_db.create_payment_request(row)
        except local_db.PaymentConflict as e:
            raise reused if "reference" in str(e).lower() else waiting
        except local_db.LocalStoreError:
            raise StorageWriteFailed("Your payment details could not be saved. Please try again.")

    logger.info(f"Payment claim | user={user_id} plan={plan} amount={row['amount_inr']} ref={ref}")
    return _public({**row, "status": "pending"})


def list_mine(db, user_id: str) -> list[dict]:
    if db:
        try:
            rows = (
                db.table("payment_requests").select(",".join(_PUBLIC_FIELDS))
                .eq("user_id", user_id).order("created_at", desc=True).limit(20).execute().data
            ) or []
        except Exception as e:
            logger.warning(f"Payment history lookup failed for {user_id}: {e}")
            raise DatabaseUnavailable()
    else:
        rows = local_db.list_payment_requests(user_id=user_id, limit=20)
    return [_public(r) for r in rows]


def _emails_for(db, user_ids: list[str]) -> dict[str, str]:
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    if db:
        try:
            rows = db.table("profiles").select("id,email").in_("id", ids).execute().data or []
            return {str(r["id"]): r.get("email") or "" for r in rows}
        except Exception as e:
            logger.warning(f"Email lookup for payments failed: {e}")
            raise DatabaseUnavailable()
    out = {}
    for uid in ids:
        user = local_db.get_user_by_id(uid)
        if user:
            out[uid] = user.get("email") or ""
    return out


def list_for_operator(db, status: str | None = "pending") -> list[dict]:
    if db:
        try:
            query = db.table("payment_requests").select("*")
            if status:
                query = query.eq("status", status)
            rows = query.order("created_at", desc=True).limit(100).execute().data or []
        except Exception as e:
            logger.warning(f"Payment list failed: {e}")
            raise DatabaseUnavailable()
    else:
        rows = local_db.list_payment_requests(status=status, limit=100)
    emails = _emails_for(db, [str(r["user_id"]) for r in rows])
    return [
        {**_public(r), "user_id": str(r["user_id"]), "email": emails.get(str(r["user_id"]), ""),
         "decided_by": r.get("decided_by")}
        for r in rows
    ]


def _get(db, request_id: str) -> dict:
    try:
        uuid.UUID(str(request_id))
    except ValueError:
        raise NotFoundError("That payment was not found.")
    if db:
        try:
            rows = db.table("payment_requests").select("*").eq("id", request_id).limit(1).execute().data or []
        except Exception as e:
            logger.warning(f"Payment lookup failed: {e}")
            raise DatabaseUnavailable()
        row = rows[0] if rows else None
    else:
        row = local_db.get_payment_request(request_id)
    if not row:
        raise NotFoundError("That payment was not found.")
    return row


def _move(db, request_id: str, to_status: str, decided_by: str | None, note: str | None,
          from_status: str = "pending") -> bool:
    """Conditional status change; False if the claim was not in `from_status`."""
    decided_at = datetime.now(timezone.utc).isoformat() if decided_by else None
    if db:
        res = (
            db.table("payment_requests")
            .update({"status": to_status, "decided_at": decided_at, "decided_by": decided_by, "note": note})
            .eq("id", request_id).eq("status", from_status).execute()
        )
        return bool(res.data)
    return local_db.decide_payment_request(request_id, to_status, decided_by or "", note, from_status=from_status)


def _already_decided(row: dict) -> ConflictError:
    return ConflictError(f"This payment was already {row.get('status')}.")


def approve(db, request_id: str, operator_email: str) -> dict:
    """Grant the plan for the paid period. Exactly once per claim."""
    row = _get(db, request_id)
    if row.get("status") != "pending":
        raise _already_decided(row)
    try:
        claimed = _move(db, request_id, "approved", operator_email, None)
    except Exception as e:
        logger.error(f"Payment approval not stored for {request_id}: {e}")
        raise StorageWriteFailed("The approval could not be saved. Nothing was changed.")
    if not claimed:
        # Someone else decided it between the read and the update.
        raise _already_decided(_get(db, request_id))

    user_id = str(row["user_id"])
    current_plan, current_end = billing.get_subscription(db, user_id)
    now = datetime.now(timezone.utc)
    start = current_end if (current_plan == row["plan"] and current_end and current_end > now) else now
    period_end = start + timedelta(days=max(1, int(settings.PLAN_PERIOD_DAYS)))
    try:
        billing.set_plan(db, user_id, row["plan"], period_end=period_end, provider="upi", reference=row["reference"])
    except Exception:
        # Put the claim back, so the operator can try again and the customer
        # is not left "approved" without the plan.
        try:
            _move(db, request_id, "pending", None, None, from_status="approved")
        except Exception as e:
            logger.critical(f"Payment {request_id} marked approved but the plan was NOT granted: {e}")
        raise StorageWriteFailed("The plan could not be granted. The payment is still waiting for approval.")

    logger.info(f"Payment approved | request={request_id} user={user_id} plan={row['plan']} until={period_end.isoformat()} by={operator_email}")
    return {"status": "approved", "plan": row["plan"], "plan_expires_at": period_end.isoformat()}


def reject(db, request_id: str, operator_email: str, note: str | None) -> dict:
    row = _get(db, request_id)
    if row.get("status") != "pending":
        raise _already_decided(row)
    clean = (note or "").strip()[:300] or None
    try:
        moved = _move(db, request_id, "rejected", operator_email, clean)
    except Exception as e:
        logger.error(f"Payment rejection not stored for {request_id}: {e}")
        raise StorageWriteFailed("The rejection could not be saved. Nothing was changed.")
    if not moved:
        raise _already_decided(_get(db, request_id))
    logger.info(f"Payment rejected | request={request_id} by={operator_email}")
    return {"status": "rejected"}
