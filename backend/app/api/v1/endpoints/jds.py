"""
HireLens — Saved Job Descriptions

A job description is written once and used against every shortlist for that
role, often over several weeks. Retyping it, or hunting for the right file each
time, is where the wrong version gets pasted — and a JD-match ranking is only
ever as good as the description it ranked against.

Deliberately not a URL fetcher. Job boards render through JavaScript and sit
behind bot protection, so fetching one usually yields a cookie banner or a
sign-in wall, and the ranking that follows is confidently wrong about every
candidate. A named, saved description is the same convenience without the
silent failure.

Stored in Supabase when configured, and in the local store otherwise — both,
so a JD survives a restart either way.
"""

import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core import local_db
from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    StorageWriteFailed,
    ValidationError,
)

logger = logging.getLogger("hirelens")
router = APIRouter()

# A recruiter with hundreds of saved descriptions has a filing problem, not a
# picker. The cap keeps the list usable and the payload small.
MAX_SAVED_JDS = 50
MIN_JD_CHARS = 30


class SaveJdRequest(BaseModel):
    name: str = Field(..., description="What this role is called, e.g. 'Senior Backend Engineer'")
    jd_text: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = " ".join((v or "").split())
        if not v:
            raise ValueError("Give this job description a name so you can find it again.")
        if len(v) > 100:
            raise ValueError("That name is too long — keep it under 100 characters.")
        return v

    @field_validator("jd_text")
    @classmethod
    def clean_text(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < MIN_JD_CHARS:
            raise ValueError(
                f"A job description needs at least {MIN_JD_CHARS} characters to match against."
            )
        # Same ceiling the matcher itself applies, so what is saved is what
        # gets used — a JD silently truncated at match time would rank against
        # text the recruiter never saw.
        return v[: settings.JD_MAX_CHARS]


def _row(record: dict) -> dict:
    """The shape the UI reads, from either store."""
    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "char_count": record.get("char_count")
        if record.get("char_count") is not None
        else len(record.get("jd_text") or ""),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "last_used_at": record.get("last_used_at"),
    }


# ── Supabase helpers ────────────────────────────────────────────────────────
def _supabase_list(db, user_id: str) -> list[dict] | None:
    try:
        res = (
            db.table("saved_jds")
            .select("id,name,jd_text,created_at,updated_at,last_used_at")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.warning(f"Saved-JD listing failed in Supabase for {user_id}: {e}")
        return None


def _supabase_get(db, jd_id: str, user_id: str) -> dict | None:
    try:
        res = (
            db.table("saved_jds")
            .select("id,name,jd_text,created_at,updated_at,last_used_at")
            .eq("id", jd_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return (res.data or None) if res else None
    except Exception as e:
        logger.warning(f"Saved-JD read failed in Supabase for {jd_id}: {e}")
        return None


# ── Routes ──────────────────────────────────────────────────────────────────
@router.get("")
async def list_saved_jds(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """Names only — the full text is fetched when one is actually chosen."""
    user_id = current_user["id"]

    if db:
        rows = _supabase_list(db, user_id)
        if rows is not None:
            return {"job_descriptions": [_row(r) for r in rows]}

    return {"job_descriptions": [_row(r) for r in local_db.list_jds(user_id)]}


@router.post("", status_code=201)
async def save_job_description(
    body: SaveJdRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Save a job description under a name, or replace the one already using it.

    Saving over an existing name is deliberate: a role's description gets
    revised, and ending up with three entries all called "Backend Engineer"
    with no way to tell them apart is worse than replacing the old text.
    """
    user_id = current_user["id"]
    jd_id = str(uuid.uuid4())

    existing = local_db.list_jds(user_id)
    if db:
        remote = _supabase_list(db, user_id)
        if remote is not None:
            existing = remote
    if len(existing) >= MAX_SAVED_JDS and not any(
        (r.get("name") or "").lower() == body.name.lower() for r in existing
    ):
        raise ConflictError(
            f"You already have {MAX_SAVED_JDS} saved job descriptions. "
            f"Delete one you no longer need before saving another."
        )

    stored: dict | None = None

    if db:
        try:
            match = next(
                (r for r in existing if (r.get("name") or "").lower() == body.name.lower()),
                None,
            )
            if match:
                # Only the text is updated. The name this description was
                # first saved under is the one the recruiter looks for, and
                # replacing it with a different casing would make the list
                # disagree with what they just saw.
                res = (
                    db.table("saved_jds")
                    .update({"jd_text": body.jd_text})
                    .eq("id", match["id"])
                    .eq("user_id", user_id)
                    .execute()
                )
            else:
                res = (
                    db.table("saved_jds")
                    .insert({
                        "id": jd_id,
                        "user_id": user_id,
                        "name": body.name,
                        "jd_text": body.jd_text,
                    })
                    .execute()
                )
            stored = (res.data or [None])[0]
        except Exception as e:
            logger.warning(f"Saved-JD write failed in Supabase ({e}) — using the local store")

    # Written locally as well as remotely: it is the durable copy when there is
    # no Supabase, and a harmless mirror when there is.
    try:
        local = local_db.save_jd(jd_id, user_id, body.name, body.jd_text)
    except local_db.LocalStoreError:
        local = None
        if stored is None:
            logger.error(f"Saved JD could not be persisted at all | user={user_id}")
            raise StorageWriteFailed(
                "That job description could not be saved. Please try again."
            )

    record = stored or local or {
        "id": jd_id, "name": body.name, "jd_text": body.jd_text,
    }
    return {"job_description": _row(record), "status": "saved"}


@router.get("/{jd_id}")
async def get_saved_jd(
    jd_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """One saved description, text included — this is what fills the box."""
    user_id = current_user["id"]

    record = _supabase_get(db, jd_id, user_id) if db else None
    if record is None:
        record = local_db.get_jd(jd_id, user_id)
    if not record:
        raise NotFoundError("That saved job description no longer exists.")

    local_db.touch_jd(jd_id, user_id)
    if db:
        try:
            from datetime import datetime, timezone
            db.table("saved_jds").update(
                {"last_used_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", jd_id).eq("user_id", user_id).execute()
        except Exception as e:
            logger.warning(f"Could not record use of JD {jd_id}: {e}")

    out = _row(record)
    out["jd_text"] = record.get("jd_text") or ""
    return {"job_description": out}


@router.delete("/{jd_id}")
async def delete_saved_jd(
    jd_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    user_id = current_user["id"]
    removed = False

    if db:
        try:
            db.table("saved_jds").delete().eq("id", jd_id).eq("user_id", user_id).execute()
            removed = True
        except Exception as e:
            logger.warning(f"Saved-JD delete failed in Supabase for {jd_id}: {e}")

    try:
        removed = local_db.delete_jd(jd_id, user_id) or removed
    except local_db.LocalStoreError:
        # "Deleted" has to mean deleted, or it comes back at the next restart.
        logger.error(f"Saved-JD deletion failed to persist | jd={jd_id}")
        raise StorageWriteFailed(
            "That job description could not be deleted. It is unchanged — please try again."
        )

    if not removed:
        raise NotFoundError("That saved job description no longer exists.")
    return {"status": "deleted"}
