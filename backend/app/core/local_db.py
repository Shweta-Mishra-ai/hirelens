"""
HireLens — Persistent Local SQLite Database
Used as a resilient, zero-config local storage for user accounts and reports
when Supabase is not configured or during local development.
Ensures users, passwords, and reports persist across server restarts.
"""

import os
import sqlite3
import hashlib
import uuid
import logging
import bcrypt
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("hirelens")

# SQLite database file inside backend/data/.
#
# Overridable via HIRELENS_LOCAL_DB_PATH so the test suite can point at a
# throwaway file. Without that override the suite wrote to the developer's
# real backend/data/local.db and leaked state between runs: the accounts
# created by the auth/e2e tests survived, so a *second* `pytest` on the same
# machine failed on "email already registered" while a fresh CI runner passed.
# Tests that only pass on a clean checkout hide real regressions behind noise.
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = Path(os.environ.get("HIRELENS_LOCAL_DB_PATH") or (DATA_DIR / "local.db"))


def _hash_pw(pw: str) -> str:
    """
    Hash a password with bcrypt (per-user random salt, deliberately slow —
    ~250ms/attempt on typical hardware at cost factor 12).

    This used to be `sha256(f"hirelens_salt_{pw}")` — a single hardcoded
    salt shared across every user, using a hash designed to be FAST.
    Both properties are the opposite of what password storage needs: a
    fast general-purpose hash lets an attacker who obtains the database
    try billions of guesses per second on commodity GPU hardware, and a
    shared static salt means one precomputed rainbow table (built once
    against "hirelens_salt_" + a common-password wordlist) cracks every
    account that used one of those passwords, in every row, at once.
    bcrypt fixes both: a fresh random salt per password, and a cost
    factor that makes each guess deliberately expensive.

    Note: passlib (also listed in requirements.txt) was never actually
    wired up here, and its bcrypt backend is broken against modern
    bcrypt>=4.0 (a known passlib/bcrypt compatibility issue — it raises
    on hash() at import-detection time). Calling bcrypt directly avoids
    that broken compatibility shim entirely.
    """
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _looks_like_legacy_sha256(hash_value: str) -> bool:
    """The old scheme stored a 64-char hex sha256 digest; bcrypt hashes are
    ~60 chars and start with $2a$/$2b$/$2y$ — trivially distinguishable."""
    return len(hash_value) == 64 and not hash_value.startswith("$")


def _legacy_sha256_hash(pw: str) -> str:
    """Reproduces the old (insecure) hash, ONLY to verify — and then
    immediately upgrade — any password hashed before this fix shipped.
    Never used to create new hashes."""
    return hashlib.sha256(f"hirelens_salt_{pw}".encode()).hexdigest()


def _get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
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

            # Seed default demo recruiter
            demo_email = "demo@hirelens.ai"
            cursor.execute("SELECT id FROM users WHERE email = ?", (demo_email,))
            if not cursor.fetchone():
                now = datetime.now(timezone.utc).isoformat()
                cursor.execute("""
                    INSERT INTO users (id, email, password_hash, full_name, company, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()),
                    demo_email,
                    _hash_pw("Password123!"),
                    "Demo Recruiter",
                    "HireLens HQ",
                    now,
                ))
            conn.commit()
            logger.info("Local SQLite database initialized and demo account ready.")
    except Exception as e:
        logger.error(f"Failed to initialize local SQLite database: {e}")


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


def verify_user_password(email: str, password: str) -> dict | None:
    user = get_user_by_email(email)
    if not user:
        return None

    stored_hash = user["password_hash"]

    if _looks_like_legacy_sha256(stored_hash):
        # Account predates this fix. Verify against the old scheme once,
        # and if it matches, transparently re-hash with bcrypt and persist
        # it — the user never notices, but their password is no longer
        # sitting in the database under a crackable scheme after this
        # single successful login.
        if stored_hash != _legacy_sha256_hash(password):
            return None
        new_hash = _hash_pw(password)
        try:
            with _get_connection() as conn:
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user["id"]))
                conn.commit()
            logger.info(f"Upgraded legacy password hash to bcrypt for user {user['id']}")
        except Exception as e:
            logger.warning(f"Could not upgrade legacy password hash for user {user['id']}: {e}")
        return user

    try:
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
            return user
    except ValueError as e:
        # Malformed/corrupt stored hash — fail closed, not open.
        logger.warning(f"Password hash verification error for user {user['id']}: {e}")
    return None


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
            _hash_pw(password),
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
