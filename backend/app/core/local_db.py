"""
HireLens — Persistent Local SQLite Database

Zero-config local storage for user accounts when Supabase is not configured.
This is a development and single-node fallback, not a substitute for the
primary database: it has no replication and no connection pooling.

Two things changed here from the original implementation:

1. Passwords are hashed with bcrypt via ``app.core.security`` instead of an
   unsalted SHA-256 with a hardcoded constant. See that module for why the
   old scheme was not a password hash. Existing rows still verify, and are
   upgraded in place the next time their owner logs in.

2. The database path is resolved at call time from ``HIRELENS_LOCAL_DB_PATH``
   rather than being frozen into a module constant at import. Tests point it
   at a temp directory; without that, every test run mutated (and was
   affected by) a real file in the working tree, so the suite only passed on
   a clean checkout.
"""

import os
import sqlite3
import hashlib
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

from app.core.security import hash_password, verify_password, needs_rehash

logger = logging.getLogger("hirelens")

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "local.db"

# Kept as module attributes because existing callers and tests import them.
DATA_DIR = _DEFAULT_DB_PATH.parent
DB_PATH = _DEFAULT_DB_PATH


def _db_path() -> Path:
    """
    Resolve the SQLite file location. ``HIRELENS_LOCAL_DB_PATH`` wins so a
    test session (or a container with a mounted volume) can redirect it
    without touching the repository working tree.
    """
    override = os.environ.get("HIRELENS_LOCAL_DB_PATH")
    return Path(override) if override else _DEFAULT_DB_PATH


def _get_connection():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


class LocalStoreError(Exception):
    """The local store could not carry out a write.

    Raised only by the helpers whose failure a caller must not mistake for
    "there was nothing to do". A delete that removes no rows because none
    matched is a fine outcome and returns False; a delete that failed because
    the database could not be written is not, and telling someone their data
    or someone else's access is gone when it is not is the failure this exists
    to prevent.
    """


def init_local_db():
    """Initializes tables and seeds default demo recruiter if not present."""
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    company TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    file_name TEXT,
                    candidate_name TEXT,
                    overall_score INTEGER DEFAULT 0,
                    recommendation TEXT DEFAULT 'manual_review',
                    recruiter_decision TEXT,
                    report_data TEXT,
                    created_at TEXT NOT NULL,
                    job_id TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            """)

            # Existing databases predate job_id. Without it, a report whose
            # analysis job fell out of memory cannot be matched back to the
            # upload that produced it — see find_report_by_job below.
            existing = {row[1] for row in cursor.execute("PRAGMA table_info(reports)")}
            if "job_id" not in existing:
                cursor.execute("ALTER TABLE reports ADD COLUMN job_id TEXT")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_job_id ON reports(job_id)"
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id)"
            )
            conn.commit()
            logger.info("Local SQLite database initialized at %s", _db_path())
    except Exception as e:
        logger.error(f"Failed to initialize local SQLite database: {e}")


# NOTE: no account is ever seeded here. Seeding a demo login would create it
# in any deployment where Supabase is unconfigured or unreachable — including
# production, since the local store is exactly the path a misconfigured or
# degraded deploy takes — and a credential published in source that opens
# candidate reports is a backdoor whatever it was meant for. Accounts are
# created through /api/v1/auth/signup.


def get_user_by_email(email: str) -> dict | None:
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error fetching user by email from SQLite: {e}")
        return None


def get_user_by_id(user_id: str) -> dict | None:
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error fetching user by ID from SQLite: {e}")
        return None


def update_password_hash(user_id: str, new_hash: str) -> None:
    """Replace a stored hash in place — used to upgrade legacy hashes."""
    try:
        with _get_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Could not upgrade password hash for {user_id}: {e}")


def verify_user_password(email: str, password: str) -> dict | None:
    """
    Verify a login. Returns the user row on success, None otherwise.

    When the stored hash uses a superseded scheme and the password is
    correct, it is re-hashed with the current one before returning — so
    legacy rows drain away as users log in, without a migration window.
    """
    user = get_user_by_email(email)
    if not user:
        return None

    stored = user.get("password_hash") or ""
    if not verify_password(password, stored):
        return None

    if needs_rehash(stored):
        logger.info("Upgrading stored password hash for user %s", user["id"])
        update_password_hash(user["id"], hash_password(password))

    return user


def create_user(email: str, password: str, full_name: str, company: str = "") -> dict:
    email_clean = email.lower().strip()
    uid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (id, email, password_hash, full_name, company, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            uid,
            email_clean,
            hash_password(password),
            full_name.strip(),
            company.strip() if company else "",
            now,
        ))
        conn.commit()
    return {
        "id": uid,
        "email": email_clean,
        "full_name": full_name.strip(),
        "company": company.strip() if company else "",
        "created_at": now,
    }


def count_users() -> int:
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM users")
            row = cursor.fetchone()
            return row["count"] if row else 0
    except Exception:
        return 0


# Initialisation happens at the BOTTOM of this module, not here. Every table
# helper has to be defined before the init calls run, and one sitting mid-file
# would leave anything declared below it undefined at call time.
_INIT_AT_MODULE_BOTTOM = True


# ── Reports ───────────────────────────────────────────────────────────────────
#
# What makes the SQLite fallback an actual store rather than a cache.
#
# Without these, a deployment running without Supabase keeps analysed reports
# only in `analysis._jobs`, a process-local dict. On Render's free tier the
# container sleeps after ~15 minutes idle, restarts on the next request, and
# restarts again on every redeploy — so a recruiter could analyse fifty
# candidates in the morning and find an empty dashboard after lunch, with no
# error and nothing to recover.
#
# It is still a single-node fallback; Supabase remains the right answer for a
# multi-instance deployment. But it means "no database configured" degrades to
# "slower and single-node" rather than "loses your work".


def save_report(
    report_id: str,
    user_id: str,
    file_name: str,
    candidate_name: str,
    overall_score: int,
    recommendation: str,
    report_data: dict,
    created_at: str | None = None,
    job_id: str | None = None,
) -> bool:
    """
    Persist (or replace) a report. Returns True on success.

    Never raises: a storage failure must not lose the in-memory copy the
    caller is still holding, and the caller has no better recovery than to
    carry on and log.
    """
    try:
        with _get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reports
                    (id, user_id, file_name, candidate_name, overall_score,
                     recommendation, recruiter_decision, report_data, created_at, job_id)
                VALUES (?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT recruiter_decision FROM reports WHERE id = ?), NULL),
                        ?, ?, ?)
                """,
                (
                    report_id,
                    user_id,
                    file_name or "",
                    candidate_name or "Unknown",
                    int(overall_score or 0),
                    recommendation or "manual_review",
                    report_id,  # preserve any decision already recorded
                    json.dumps(report_data, default=str),
                    created_at or datetime.now(timezone.utc).isoformat(),
                    job_id,
                ),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Could not persist report {report_id}: {e}")
        return False


def find_report_by_job(job_id: str, user_id: str) -> dict | None:
    """
    The report an analysis job produced, looked up by the job id.

    Analysis progress lives in a process-local dict, so a restart — which on
    a free tier happens on every deploy and every wake from sleep — loses it
    while the finished report sits safely in storage. Polling then answered
    404 and the recruiter was told to upload again, paying for a second
    analysis of a CV that had already been analysed. This is how the status
    endpoint finds it instead.
    """
    if not job_id:
        return None
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT id, file_name FROM reports WHERE job_id = ? AND user_id = ?",
                (job_id, user_id),
            ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Could not look up the report for job {job_id}: {e}")
        return None


def get_report(report_id: str, user_id: str) -> dict | None:
    """
    Load one report, scoped to its owner.

    `user_id` is part of the query rather than checked afterwards so that a
    wrong owner and a missing row are indistinguishable to the caller — there
    is no way to use this to probe which report ids exist.
    """
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM reports WHERE id = ? AND user_id = ?", (report_id, user_id)
            ).fetchone()
        if not row:
            return None

        record = dict(row)
        try:
            data = json.loads(record.get("report_data") or "{}")
        except json.JSONDecodeError as e:
            logger.error(f"Report {report_id} has unreadable report_data: {e}")
            return None

        data["id"] = record["id"]
        data["file_name"] = record.get("file_name") or data.get("file_name") or ""
        data["created_at"] = record.get("created_at") or ""
        data["recruiter_decision"] = record.get("recruiter_decision")
        data["_owner_user_id"] = record["user_id"]
        return data
    except Exception as e:
        logger.error(f"Could not load report {report_id}: {e}")
        return None


def list_reports(user_id: str) -> list[dict]:
    """Summary rows for one user's reports, newest first."""
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, file_name, candidate_name, overall_score,
                       recommendation, recruiter_decision, created_at
                FROM reports WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not list reports for {user_id}: {e}")
        return []


def set_report_decision(report_id: str, user_id: str, decision: str | None) -> bool:
    try:
        with _get_connection() as conn:
            cur = conn.execute(
                "UPDATE reports SET recruiter_decision = ? WHERE id = ? AND user_id = ?",
                (decision, report_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Could not record decision on {report_id}: {e}")
        return False


def delete_report(report_id: str, user_id: str) -> bool:
    try:
        with _get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM reports WHERE id = ? AND user_id = ?", (report_id, user_id)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Could not delete report {report_id}: {e}")
        raise LocalStoreError(str(e)) from e


def count_reports(user_id: str | None = None) -> int:
    try:
        with _get_connection() as conn:
            if user_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM reports WHERE user_id = ?", (user_id,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM reports").fetchone()
        return row["c"] if row else 0
    except Exception:
        return 0


# ── Co-pilot evaluations ─────────────────────────────────────────────────────
#
# Interview notes and scorecards live beside the report they belong to, scoped
# to the owner in the query. A module-level dict keyed by report id would lose
# them on every restart and carry no owner to authorize a read against.


def save_copilot(report_id: str, user_id: str, payload: dict) -> bool:
    """Attach co-pilot data to a report the user owns. False if not theirs."""
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT report_data FROM reports WHERE id = ? AND user_id = ?",
                (report_id, user_id),
            ).fetchone()
            if not row:
                return False
            try:
                data = json.loads(row["report_data"] or "{}")
            except json.JSONDecodeError:
                data = {}
            data["copilot_data"] = payload
            conn.execute(
                "UPDATE reports SET report_data = ? WHERE id = ? AND user_id = ?",
                (json.dumps(data, default=str), report_id, user_id),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Could not save co-pilot data for {report_id}: {e}")
        return False


def get_copilot(report_id: str, user_id: str) -> dict | None:
    """Co-pilot data for a report the user owns, or None."""
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT report_data FROM reports WHERE id = ? AND user_id = ?",
                (report_id, user_id),
            ).fetchone()
        if not row:
            return None
        try:
            return (json.loads(row["report_data"] or "{}") or {}).get("copilot_data") or {}
        except json.JSONDecodeError:
            return {}
    except Exception as e:
        logger.error(f"Could not load co-pilot data for {report_id}: {e}")
        return None


# ── Collaboration: comments and votes ────────────────────────────────────────


def init_collaboration_tables() -> None:
    try:
        with _get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS report_comments (
                    id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS report_votes (
                    report_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    vote TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (report_id, user_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_comments_report ON report_comments(report_id)"
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Could not initialise collaboration tables: {e}")


def add_comment(report_id: str, user_id: str, comment: str) -> dict | None:
    try:
        cid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with _get_connection() as conn:
            conn.execute(
                "INSERT INTO report_comments (id, report_id, user_id, comment, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (cid, report_id, user_id, comment, now),
            )
            conn.commit()
        return {
            "id": cid, "report_id": report_id, "user_id": user_id,
            "comment": comment, "created_at": now,
        }
    except Exception as e:
        logger.error(f"Could not add comment to {report_id}: {e}")
        return None


def list_comments(report_id: str) -> list[dict]:
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM report_comments WHERE report_id = ? ORDER BY created_at ASC",
                (report_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not list comments for {report_id}: {e}")
        return []


def delete_comment(comment_id: str, user_id: str) -> bool:
    """Only the comment's author may delete it."""
    try:
        with _get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM report_comments WHERE id = ? AND user_id = ?",
                (comment_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Could not delete comment {comment_id}: {e}")
        return False


def cast_vote(report_id: str, user_id: str, vote: str) -> bool:
    """One vote per user per report; re-voting replaces the previous one."""
    try:
        with _get_connection() as conn:
            conn.execute(
                "INSERT INTO report_votes (report_id, user_id, vote, created_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(report_id, user_id) DO UPDATE SET vote = excluded.vote,"
                " created_at = excluded.created_at",
                (report_id, user_id, vote, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Could not record vote on {report_id}: {e}")
        return False


def list_votes(report_id: str) -> list[dict]:
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT report_id, user_id, vote FROM report_votes WHERE report_id = ?",
                (report_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not list votes for {report_id}: {e}")
        return []



def list_reports_any_owner(report_id: str) -> list[dict]:
    """
    Look up a report by id without scoping to an owner.

    Used only where the caller needs the owner in order to run its own
    access check (collaboration's `_fetch_report_row`). Every user-facing
    read path should use `get_report`, which scopes by owner in the query.
    """
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT id, user_id, candidate_name FROM reports WHERE id = ?", (report_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not look up report {report_id}: {e}")
        return []


def get_display_names(user_ids: list[str]) -> dict[str, dict]:
    """
    Map user ids to something a person can read.

    Comment threads and team member lists were rendering the raw UUID as the
    author's name, and an avatar built from the first characters of that
    UUID — so a teammate showed up as "F1" / "8c3f1a2e-...". The names have
    been in this table all along; nothing was reading them.

    Ids that cannot be resolved are simply absent from the result, and the
    caller is expected to fall back to a neutral label rather than printing
    the id.
    """
    ids = [str(u) for u in dict.fromkeys(user_ids) if u]
    if not ids:
        return {}
    try:
        with _get_connection() as conn:
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"SELECT id, full_name, email FROM users WHERE id IN ({placeholders})", ids
            ).fetchall()
        return {
            r["id"]: {"full_name": r["full_name"] or "", "email": r["email"] or ""}
            for r in rows
        }
    except Exception as e:
        logger.error(f"Could not resolve display names: {e}")
        return {}


# ── Teams ────────────────────────────────────────────────────────────────────
#
# Teams, memberships and invites, kept on disk rather than in the process-local
# lists in services/teams/access.py. A team that lives only in memory vanishes
# on the next restart, taking its membership with it and leaving any report
# already shared to it pointing at a team_id that no longer resolves.


def init_team_tables() -> None:
    try:
        with _get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS teams (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS team_members (
                    team_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY (team_id, user_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS team_invites (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_team_invites_email ON team_invites(email)"
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Could not initialise team tables: {e}")


def create_team(team_id: str, name: str, owner_id: str, created_at: str | None = None) -> bool:
    now = created_at or datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO teams (id, name, owner_id, created_at) VALUES (?, ?, ?, ?)",
                (team_id, name, owner_id, now),
            )
            conn.execute(
                "INSERT OR REPLACE INTO team_members (team_id, user_id, role, joined_at)"
                " VALUES (?, ?, 'owner', ?)",
                (team_id, owner_id, now),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Could not persist team {team_id}: {e}")
        return False


def list_teams_for_user(user_id: str) -> list[dict]:
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                """
                SELECT t.id, t.name, t.owner_id, t.created_at, m.role AS my_role
                FROM teams t
                JOIN team_members m ON m.team_id = t.id
                WHERE m.user_id = ?
                ORDER BY t.created_at ASC
                """,
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not list teams for {user_id}: {e}")
        return []


def get_team_role(team_id: str, user_id: str) -> str | None:
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT role FROM team_members WHERE team_id = ? AND user_id = ?",
                (team_id, user_id),
            ).fetchone()
        return row["role"] if row else None
    except Exception as e:
        logger.error(f"Could not read team role: {e}")
        return None


def list_team_members(team_id: str) -> list[dict]:
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT team_id, user_id, role, joined_at FROM team_members WHERE team_id = ?"
                " ORDER BY joined_at ASC",
                (team_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not list members of {team_id}: {e}")
        return []


def add_team_member(team_id: str, user_id: str, role: str = "member") -> bool:
    try:
        with _get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO team_members (team_id, user_id, role, joined_at)"
                " VALUES (?, ?, ?, ?)",
                (team_id, user_id, role, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Could not add member to {team_id}: {e}")
        return False


def remove_team_member(team_id: str, user_id: str) -> bool:
    try:
        with _get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, user_id)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Could not remove member from {team_id}: {e}")
        raise LocalStoreError(str(e)) from e


def delete_team(team_id: str, owner_id: str) -> bool:
    """
    Remove a team, everyone in it, and any invite still outstanding.

    All three, not just the team row. Touching only this process's caches
    leaves the team and its whole roster on disk, to come back on the next
    restart — and membership that outlives its team is an access question,
    since a report stamped with that team_id stays readable to anyone whose
    membership row survived.
    """
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT owner_id FROM teams WHERE id = ?", (team_id,)
            ).fetchone()
            if not row or row["owner_id"] != owner_id:
                return False
            conn.execute("DELETE FROM team_members WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM team_invites WHERE team_id = ?", (team_id,))
            conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Could not delete team {team_id}: {e}")
        raise LocalStoreError(str(e)) from e


def create_invite(invite_id: str, team_id: str, email: str) -> bool:
    try:
        with _get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO team_invites (id, team_id, email, status, created_at)"
                " VALUES (?, ?, ?, 'pending', ?)",
                (invite_id, team_id, email.lower().strip(), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Could not create invite for {email}: {e}")
        return False


def find_pending_invite(team_id: str, email: str) -> dict | None:
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM team_invites WHERE team_id = ? AND email = ? AND status = 'pending'",
                (team_id, email.lower().strip()),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def list_pending_invites(team_id: str) -> list[dict]:
    """
    Who has been invited to this team and not joined yet.

    Without this the owner had no idea an invite existed: the roster showed
    only people who had already joined, so an invite that was mistyped, or
    that the person never acted on, was invisible — and re-inviting the same
    address just answered "already invited" with nothing to look at.
    """
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT id, email, created_at FROM team_invites "
                "WHERE team_id = ? AND status = 'pending' ORDER BY created_at",
                (team_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not list invites for team {team_id}: {e}")
        return []


def revoke_invite(invite_id: str, team_id: str) -> bool:
    """Withdraw a pending invite. Scoped to the team so an id alone is not enough."""
    try:
        with _get_connection() as conn:
            cur = conn.execute(
                "UPDATE team_invites SET status = 'revoked' "
                "WHERE id = ? AND team_id = ? AND status = 'pending'",
                (invite_id, team_id),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Could not revoke invite {invite_id}: {e}")
        return False


def accept_invites_for_email(email: str, user_id: str) -> int:
    """Join every team this address was invited to. Returns how many."""
    accepted = 0
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT id, team_id FROM team_invites WHERE email = ? AND status = 'pending'",
                (email.lower().strip(),),
            ).fetchall()
            now = datetime.now(timezone.utc).isoformat()
            for row in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO team_members (team_id, user_id, role, joined_at)"
                    " VALUES (?, ?, 'member', ?)",
                    (row["team_id"], user_id, now),
                )
                conn.execute(
                    "UPDATE team_invites SET status = 'accepted' WHERE id = ?", (row["id"],)
                )
                accepted += 1
            conn.commit()
    except Exception as e:
        logger.error(f"Could not accept invites for {email}: {e}")
    return accepted



# ── Password resets (local store only) ───────────────────────────────────────
#
# Supabase owns this flow when it is configured. Without it there is no
# provider to send a recovery link, and an account whose password is forgotten
# would be lost for good — so the local store issues its own single-use token.
#
# Only the SHA-256 of the token is stored. A reset token is a bearer
# credential: anyone holding one can take over the account, so a leaked
# database file must not hand over working tokens. The token itself exists
# only in the email.


def init_password_reset_table() -> None:
    try:
        with _get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS password_resets (
                    token_hash  TEXT PRIMARY KEY,
                    user_id     TEXT NOT NULL,
                    expires_at  TEXT NOT NULL,
                    used_at     TEXT,
                    created_at  TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_password_resets_user ON password_resets (user_id)"
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to initialize password_resets table: {e}")


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_password_reset(user_id: str, token: str, ttl_seconds: int) -> bool:
    """Issue a reset token, replacing any the user already has.

    Outstanding tokens are invalidated first: asking for a second link has to
    mean the first one stops working, or an old email forwarded to someone
    else stays usable."""
    now = datetime.now(timezone.utc)
    try:
        with _get_connection() as conn:
            conn.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
            conn.execute(
                "INSERT INTO password_resets (token_hash, user_id, expires_at, created_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    _hash_reset_token(token),
                    user_id,
                    (now + timedelta(seconds=ttl_seconds)).isoformat(),
                    now.isoformat(),
                ),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Could not create password reset for {user_id}: {e}")
        return False


def consume_password_reset(token: str, new_password: str) -> str | None:
    """
    Spend a reset token and set the new password. Returns the user id, or
    None when the token is unknown, expired or already used.

    The whole thing runs in one transaction, so a token cannot be redeemed
    twice by two requests arriving together.
    """
    now = datetime.now(timezone.utc)
    try:
        with _get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT user_id, expires_at, used_at FROM password_resets WHERE token_hash = ?",
                (_hash_reset_token(token),),
            ).fetchone()

            if not row or row["used_at"]:
                conn.rollback()
                return None
            try:
                expires_at = datetime.fromisoformat(row["expires_at"])
            except ValueError:
                conn.rollback()
                return None
            if expires_at <= now:
                conn.rollback()
                return None

            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(new_password), row["user_id"]),
            )
            conn.execute(
                "UPDATE password_resets SET used_at = ? WHERE token_hash = ?",
                (now.isoformat(), _hash_reset_token(token)),
            )
            conn.commit()
            return row["user_id"]
    except Exception as e:
        logger.error(f"Could not consume password reset token: {e}")
        return None


def purge_expired_password_resets() -> int:
    """Drop spent and expired tokens. Called opportunistically."""
    try:
        with _get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM password_resets WHERE expires_at <= ? OR used_at IS NOT NULL",
                (datetime.now(timezone.utc).isoformat(),),
            )
            conn.commit()
            return cur.rowcount or 0
    except Exception:
        return 0


# ── Saved job descriptions ───────────────────────────────────────────────────
#
# A job description is written once and used against every shortlist for that
# role, often over weeks. Retyping or re-locating the file each time is where
# the wrong version gets pasted — and a JD-match ranking is only as good as the
# description it ranked against.


def init_saved_jd_table() -> None:
    try:
        with _get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_jds (
                    id          TEXT PRIMARY KEY,
                    user_id     TEXT NOT NULL,
                    name        TEXT NOT NULL,
                    jd_text     TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    last_used_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_saved_jds_user ON saved_jds (user_id, updated_at DESC)"
            )
            # One name per recruiter, so saving over "Senior Backend Engineer"
            # replaces it rather than leaving two entries with the same label
            # and no way to tell them apart.
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_jds_user_name"
                " ON saved_jds (user_id, name COLLATE NOCASE)"
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to initialize saved_jds table: {e}")


def save_jd(jd_id: str, user_id: str, name: str, jd_text: str) -> dict | None:
    """Create or replace a saved JD. Returns the stored row."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection() as conn:
            existing = conn.execute(
                "SELECT id, name, created_at FROM saved_jds WHERE user_id = ? AND name = ? COLLATE NOCASE",
                (user_id, name),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE saved_jds SET jd_text = ?, updated_at = ? WHERE id = ?",
                    (jd_text, now, existing["id"]),
                )
                row_id, created = existing["id"], existing["created_at"]
                # Keep the spelling this description was first saved under.
                # Echoing back whatever casing was typed this time would show
                # one name on save and a different one on the next reload.
                name = existing["name"]
            else:
                conn.execute(
                    "INSERT INTO saved_jds (id, user_id, name, jd_text, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (jd_id, user_id, name, jd_text, now, now),
                )
                row_id, created = jd_id, now
            conn.commit()
        return {
            "id": row_id, "name": name, "jd_text": jd_text,
            "created_at": created, "updated_at": now,
            "char_count": len(jd_text),
        }
    except Exception as e:
        logger.error(f"Could not save JD for {user_id}: {e}")
        raise LocalStoreError(str(e)) from e


def list_jds(user_id: str) -> list[dict]:
    """Every saved JD for this recruiter, most recently updated first.

    The text itself is left out — a list of twenty job descriptions is a lot to
    send to render a picker that only shows names."""
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT id, name, created_at, updated_at, last_used_at, LENGTH(jd_text) AS char_count"
                " FROM saved_jds WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not list JDs for {user_id}: {e}")
        return []


def get_jd(jd_id: str, user_id: str) -> dict | None:
    """One saved JD, scoped to its owner — the id alone is never enough."""
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT id, name, jd_text, created_at, updated_at, last_used_at"
                " FROM saved_jds WHERE id = ? AND user_id = ?",
                (jd_id, user_id),
            ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["char_count"] = len(out.get("jd_text") or "")
        return out
    except Exception as e:
        logger.error(f"Could not read JD {jd_id}: {e}")
        return None


def touch_jd(jd_id: str, user_id: str) -> None:
    """Record that a JD was actually used, so the picker can lead with it."""
    try:
        with _get_connection() as conn:
            conn.execute(
                "UPDATE saved_jds SET last_used_at = ? WHERE id = ? AND user_id = ?",
                (datetime.now(timezone.utc).isoformat(), jd_id, user_id),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Could not record use of JD {jd_id}: {e}")


def delete_jd(jd_id: str, user_id: str) -> bool:
    try:
        with _get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM saved_jds WHERE id = ? AND user_id = ?", (jd_id, user_id)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Could not delete JD {jd_id}: {e}")
        raise LocalStoreError(str(e)) from e


def count_jds(user_id: str) -> int:
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM saved_jds WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(row["c"]) if row else 0
    except Exception:
        return 0


init_local_db()
init_collaboration_tables()
init_team_tables()
init_password_reset_table()
init_saved_jd_table()
