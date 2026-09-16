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
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone

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
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            """)

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id)"
            )
            conn.commit()
            logger.info("Local SQLite database initialized at %s", _db_path())
    except Exception as e:
        logger.error(f"Failed to initialize local SQLite database: {e}")


# NOTE: this used to seed a `demo@hirelens.ai` account with the fixed
# password "Password123!" on every startup. That account was created in any
# deployment where Supabase was unconfigured or unreachable — including
# production, where the Supabase fallback is exactly the path a misconfigured
# or degraded deploy takes. A publicly-known credential that grants access to
# candidate reports is a backdoor regardless of intent, so the seeding is
# gone. Create accounts through /api/v1/auth/signup.


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


# Ensure database is initialized upon import.
# NOTE: this call must stay at the BOTTOM of the module. It used to sit
# mid-file, which was fine while `init_local_db` was the only initialiser,
# but any table helper defined below it would not yet exist at call time.
_INIT_MOVED_TO_BOTTOM = True


# ── Reports ───────────────────────────────────────────────────────────────────
#
# The `reports` table has existed since the first version of this module but
# had no read or write functions, so nothing ever used it. Without Supabase,
# analysed reports lived only in `analysis._jobs` — a process-local dict. On
# Render's free tier the container sleeps after ~15 minutes idle and restarts
# on the next request, and every redeploy restarts it too, so a recruiter
# could analyse fifty candidates in the morning and find an empty dashboard
# after lunch, with no error and nothing to recover.
#
# These functions make the SQLite fallback an actual store. It is still a
# single-node fallback — Supabase remains the right answer for multi-instance
# deployments — but it means "no database configured" degrades to "slower and
# single-node" instead of "silently loses your work".


def save_report(
    report_id: str,
    user_id: str,
    file_name: str,
    candidate_name: str,
    overall_score: int,
    recommendation: str,
    report_data: dict,
    created_at: str | None = None,
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
                     recommendation, recruiter_decision, report_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT recruiter_decision FROM reports WHERE id = ?), NULL),
                        ?, ?)
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
                ),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Could not persist report {report_id}: {e}")
        return False


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
        return False


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
# Interview notes and scorecards were previously kept in a module-level dict
# keyed by report id, with no ownership check on read or write, and lost on
# every restart. Storing them beside the report — scoped to the owner in the
# query — fixes both.


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
# Teams, memberships and invites were process-local lists in
# services/teams/access.py, so a team created without Supabase disappeared on
# the next restart — taking its membership with it, and leaving any report
# already shared to that team pointing at a team_id that no longer resolved.
# Reports, comments, votes and co-pilot data all persist; this was the last
# store that did not.


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
        return False


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


init_local_db()
init_collaboration_tables()
init_team_tables()
