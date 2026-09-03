"""
HireLens — Persistent Local SQLite Database
Used as a resilient, zero-config local storage for user accounts and reports
when Supabase is not configured or during local development.
Ensures users, passwords, and reports persist across server restarts.
"""

import os
import sqlite3
import hashlib
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("hirelens")

# SQLite database file inside backend/data/
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "local.db"


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(f"hirelens_salt_{pw}".encode()).hexdigest()


def _get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
    if user and user["password_hash"] == _hash_pw(password):
        return user
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
