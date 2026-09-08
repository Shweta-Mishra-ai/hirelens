"""
Regression tests for the password-hashing security fix in
app/core/local_db.py.

Background: passwords in the local-fallback auth path were previously
hashed with sha256(f"hirelens_salt_{pw}") — a single hardcoded salt shared
across every user, using a hash designed to be fast. Both properties are
wrong for password storage: a fast hash lets a leaked database be
brute-forced at billions of guesses/second on a GPU, and a shared static
salt means one precomputed rainbow table cracks every account that reused
a common password, all at once. This is now bcrypt, with a lazy migration
path so any account created under the old scheme gets silently upgraded
on its next successful login.
"""

import uuid
import pytest
import bcrypt as bcrypt_lib

from app.core import local_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point local_db at a throwaway SQLite file so these tests never touch
    the real dev database or leave rows behind for other tests."""
    monkeypatch.setattr(local_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(local_db, "DB_PATH", tmp_path / "test_local.db")
    local_db.init_local_db()
    yield


def test_new_user_password_is_hashed_with_bcrypt_not_sha256():
    user = local_db.create_user("bcrypt_test@example.com", "CorrectHorse123!", "Test User")
    stored = local_db.get_user_by_email("bcrypt_test@example.com")

    assert stored["password_hash"].startswith("$2")  # bcrypt identifier prefix
    assert not local_db._looks_like_legacy_sha256(stored["password_hash"])
    # sanity: an actual bcrypt hash, verifiable by the bcrypt library itself
    assert bcrypt_lib.checkpw(b"CorrectHorse123!", stored["password_hash"].encode())


def test_correct_password_verifies_and_wrong_password_is_rejected():
    local_db.create_user("verify_test@example.com", "CorrectHorse123!", "Test User")

    ok = local_db.verify_user_password("verify_test@example.com", "CorrectHorse123!")
    assert ok is not None
    assert ok["email"] == "verify_test@example.com"

    bad = local_db.verify_user_password("verify_test@example.com", "WrongPassword!")
    assert bad is None


def test_legacy_sha256_hash_still_verifies_and_is_upgraded_to_bcrypt():
    """
    Regression test for the migration path: an account created before this
    fix shipped (stored_hash is the old static-salt sha256 digest) must
    still be able to log in with their existing password — and after that
    one successful login, their hash in the database must have been
    silently upgraded to bcrypt, so it's no longer sitting there crackable.
    """
    email = "legacy_user@example.com"
    password = "OldSchemePassword1!"
    legacy_hash = local_db._legacy_sha256_hash(password)

    uid = str(uuid.uuid4())
    with local_db._get_connection() as conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, full_name, company, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (uid, email, legacy_hash, "Legacy User", ""),
        )
        conn.commit()

    # Confirm the fixture actually inserted the OLD-style hash, not bcrypt —
    # otherwise this test would pass for the wrong reason.
    before = local_db.get_user_by_email(email)
    assert local_db._looks_like_legacy_sha256(before["password_hash"])

    # First login: verifies against the legacy hash and must succeed.
    result = local_db.verify_user_password(email, password)
    assert result is not None

    # The stored hash must now be bcrypt, not the legacy sha256 digest.
    after = local_db.get_user_by_email(email)
    assert not local_db._looks_like_legacy_sha256(after["password_hash"])
    assert after["password_hash"].startswith("$2")

    # Second login must still work, now going through the bcrypt path.
    result2 = local_db.verify_user_password(email, password)
    assert result2 is not None

    # And the wrong password must still be rejected post-upgrade.
    assert local_db.verify_user_password(email, "totally wrong") is None


def test_two_users_with_the_same_password_get_different_hashes():
    """
    The old scheme used one hardcoded salt for everyone, so identical
    passwords produced identical hashes — visible to anyone who saw the
    database, and exactly what a rainbow-table attack exploits. bcrypt
    generates a fresh random salt per call, so this must no longer be true.
    """
    local_db.create_user("user_a@example.com", "SharedPassword123!", "User A")
    local_db.create_user("user_b@example.com", "SharedPassword123!", "User B")

    hash_a = local_db.get_user_by_email("user_a@example.com")["password_hash"]
    hash_b = local_db.get_user_by_email("user_b@example.com")["password_hash"]

    assert hash_a != hash_b


def test_signup_rejects_passwords_longer_than_72_bytes():
    """
    bcrypt only examines the first 72 bytes of a password input and
    silently ignores the rest — without a length check, two passwords that
    differ only after byte 72 would hash identically and both would
    authenticate. The API must reject rather than silently truncate.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    too_long = "A" * 73
    res = client.post(
        "/api/v1/auth/signup",
        json={"email": "toolong@example.com", "password": too_long, "full_name": "Too Long"},
    )
    assert res.status_code == 422


def test_auth_module_mem_store_also_uses_bcrypt_not_sha256():
    """
    auth.py had its OWN separate copy of the same insecure static-salt
    sha256 scheme, used for the in-memory `_mem_users` fallback store.
    Same fix, same test shape, different module.
    """
    from app.api.v1.endpoints import auth as auth_module

    h = auth_module._hash_pw("SomePassword123!")
    assert h.startswith("$2")
    assert auth_module._verify_mem_pw("SomePassword123!", h)
    assert not auth_module._verify_mem_pw("WrongPassword!", h)
