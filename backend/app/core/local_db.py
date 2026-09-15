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


# Ensure database is initialized upon import
init_local_db()
