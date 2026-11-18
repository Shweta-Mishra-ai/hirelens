"""
HireLens — Plans and usage.

GET  /billing/usage         this account's plan, quota and usage this month
POST /billing/admin/plan    operator: move an account to a plan

Payment collection is deliberately outside this module. Until a payment
provider is wired to a webhook, an operator records an upgrade here after a
customer pays (any provider, invoice or bank transfer). The quota takes
effect on the customer's next upload.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from app.api.v1.endpoints.analysis import _jobs
from app.core import local_db
from app.core.dependencies import get_current_user, get_db, require_admin
from app.core.exceptions import NotFoundError
from app.services import billing
from app.services.teams.access import normalize_email

logger = logging.getLogger("hirelens")
router = APIRouter()


@router.get("/usage")
def get_usage(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    return billing.usage_summary(db, current_user["id"], _jobs)


class SetPlanRequest(BaseModel):
    email: EmailStr
    plan: Literal["free", "pro", "team"]


def _user_id_for_email(db, email: str) -> str | None:
    if db:
        try:
            res = db.table("profiles").select("id").eq("email", email).limit(1).execute()
            rows = res.data or []
            if rows:
                return str(rows[0]["id"])
        except Exception as e:
            logger.warning(f"Profile lookup by email failed: {e}")
    user = local_db.get_user_by_email(email)
    return user["id"] if user else None


@router.post("/admin/plan")
def set_plan(body: SetPlanRequest, admin: dict = Depends(require_admin), db=Depends(get_db)):
    email = normalize_email(str(body.email))
    user_id = _user_id_for_email(db, email)
    if not user_id:
        raise NotFoundError("No account exists for that email address.")
    billing.set_plan(db, user_id, body.plan)
    logger.info(f"Plan changed | user={user_id} plan={body.plan} by={admin.get('email')}")
    return {"status": "ok", "user_id": user_id, "plan": body.plan}
