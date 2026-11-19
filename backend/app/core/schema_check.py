"""
Is the database schema this code expects actually there?

The migrations in backend/sql are run by hand in the Supabase SQL editor, so
deploying new code before running a new file is easy — and almost nothing
fails loudly when that happens. Every caller degrades on purpose, which is
right for an outage and wrong for a missing table: without 007, usage counts
read as zero and plan limits are silently never enforced; without 008,
"sign out of all devices" fails. The service looks healthy throughout.

So the API checks for itself: each table and column the code uses is probed
with a zero-row select, anything missing is mapped to the SQL file that
creates it, and the result goes to the log at startup (CRITICAL, naming the
files to run) and to /health.

A probe that fails for any other reason — Supabase unreachable, a bad key —
makes the result "unknown", never "missing": telling an operator to run a
migration that is already there sends them the wrong way.

Not detectable this way, and so not checked: 004 (a data fix), 006 (indexes
and policies) and the foreign-key change in 008. Each file is idempotent;
when in doubt, run it again.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger("hirelens")

# (migration file, table, columns the code reads or writes). Kept in step with
# backend/sql — the real-database test suite runs every migration and then
# asserts this check passes, so a drift between the two fails CI.
REQUIREMENTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("001_core_schema.sql", "reports", (
        "id", "user_id", "job_id", "file_name", "candidate_name", "overall_score",
        "recommendation", "report_data", "recruiter_decision", "created_at",
    )),
    ("001_core_schema.sql", "profiles", ("id", "email", "full_name", "company")),
    ("002_team_collaboration.sql", "teams", ("id", "name", "owner_id")),
    ("002_team_collaboration.sql", "team_members", ("team_id", "user_id", "role")),
    ("002_team_collaboration.sql", "team_invites", ("id", "team_id", "email", "invited_by", "status")),
    ("002_team_collaboration.sql", "report_comments", ("id", "report_id", "user_id", "comment")),
    ("002_team_collaboration.sql", "report_votes", ("report_id", "user_id", "vote")),
    ("002_team_collaboration.sql", "reports", ("team_id",)),
    ("003_candidate_notifications.sql", "reports", ("candidate_notified_at", "candidate_notified_decision")),
    ("005_saved_job_descriptions.sql", "saved_jds", ("id", "user_id", "name", "jd_text", "last_used_at")),
    ("007_billing_and_usage.sql", "subscriptions", ("user_id", "plan", "status", "current_period_end")),
    ("007_billing_and_usage.sql", "usage_events", ("id", "user_id", "kind", "report_id", "created_at")),
    ("008_sessions_and_invite_fk.sql", "session_revocations", ("user_id", "revoked_before")),
    ("009_account_deletion.sql", "deleted_accounts", ("user_id", "deleted_at")),
)

# What stops working without each file, for the startup log.
CONSEQUENCES = {
    "001_core_schema.sql": "reports and accounts cannot be stored at all",
    "002_team_collaboration.sql": "teams, invites, comments and votes fail",
    "003_candidate_notifications.sql": "candidate emails are sent but not recorded as sent",
    "005_saved_job_descriptions.sql": "saved job descriptions fail",
    "007_billing_and_usage.sql": "usage is not recorded and plan limits are NOT enforced",
    "008_sessions_and_invite_fk.sql": (
        "'Sign out of all devices' fails and a password reset cannot end old sessions"
    ),
    "009_account_deletion.sql": "people cannot delete their own account",
}

_MISSING_TABLE_CODES = {"PGRST205", "42P01"}
_MISSING_COLUMN_CODES = {"42703", "PGRST204"}
_COLUMN_IN_MESSAGE = re.compile(r"column\s+(?:[\w\"]+\.)?\"?(\w+)\"?\s+does not exist", re.IGNORECASE)

CACHE_SECONDS = 600


@dataclass
class SchemaReport:
    status: str  # "ok" | "missing" | "unknown"
    # migration file -> what is missing ("usage_events", "reports.team_id")
    missing: dict[str, list[str]] = field(default_factory=dict)
    # table -> provider error text, for probes that failed for another reason
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def public_status(self) -> str:
        return {"ok": "ok", "missing": "missing_migrations"}.get(self.status, "unknown")

    def describe(self) -> str:
        lines = []
        for migration, items in self.missing.items():
            lines.append(
                f"{migration} (missing: {', '.join(items)}) — "
                f"{CONSEQUENCES.get(migration, 'some features fail')}"
            )
        return "; ".join(lines)


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code:
        return str(code)
    match = re.search(r"\b(PGRST\d{3}|42P01|42703)\b", str(exc))
    return match.group(1) if match else ""


def _classify(exc: Exception) -> str:
    """'table', 'column' or 'other'."""
    code = _error_code(exc)
    text = str(getattr(exc, "message", "") or exc).lower()
    if code in _MISSING_TABLE_CODES or "could not find the table" in text or (
        "relation" in text and "does not exist" in text
    ):
        return "table"
    if code in _MISSING_COLUMN_CODES or ("column" in text and "does not exist" in text):
        return "column"
    return "other"


def check(db) -> SchemaReport:
    """Probe every requirement now. Never raises."""
    if db is None:
        return SchemaReport(status="unknown", errors={"database": "not configured"})

    missing: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    missing_tables: set[str] = set()

    for migration, table, columns in REQUIREMENTS:
        if table in missing_tables:
            continue
        try:
            db.table(table).select(",".join(columns)).limit(0).execute()
        except Exception as exc:  # noqa: BLE001 — classified below
            kind = _classify(exc)
            if kind == "table":
                missing_tables.add(table)
                # A table is created by the earliest file that names it.
                owner = next(m for m, t, _ in REQUIREMENTS if t == table)
                missing.setdefault(owner, []).append(table)
            elif kind == "column":
                found = _COLUMN_IN_MESSAGE.search(str(getattr(exc, "message", "") or exc))
                absent = [found.group(1)] if found and found.group(1) in columns else list(columns)
                missing.setdefault(migration, []).extend(f"{table}.{c}" for c in absent)
            else:
                errors[table] = str(exc)

    if missing:
        status = "missing"
    elif errors:
        status = "unknown"
    else:
        status = "ok"
    return SchemaReport(status=status, missing=missing, errors=errors)


_lock = threading.Lock()
_cached: tuple[float, SchemaReport] | None = None


def cached(db, max_age: float = CACHE_SECONDS) -> SchemaReport:
    """The last result if it is recent, otherwise a fresh check."""
    global _cached
    with _lock:
        if _cached and time.monotonic() - _cached[0] < max_age:
            return _cached[1]
    report = check(db)
    with _lock:
        _cached = (time.monotonic(), report)
    return report


def clear_cache() -> None:
    global _cached
    with _lock:
        _cached = None


def log_report(report: SchemaReport) -> None:
    if report.status == "missing":
        logger.critical(
            "DATABASE IS MISSING MIGRATIONS. Run these files from backend/sql in "
            "the Supabase SQL editor, in order, then redeploy or wait 10 minutes: "
            + report.describe()
        )
    elif report.status == "unknown":
        logger.warning(
            "Could not verify the database schema (%s). The check runs again with "
            "the next health check.",
            "; ".join(f"{t}: {e}" for t, e in report.errors.items())[:500],
        )
    else:
        logger.info("Database schema: every migration this code needs is present.")
