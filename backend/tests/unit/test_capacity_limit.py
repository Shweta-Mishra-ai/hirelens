"""
Registration capacity limit.

Two earlier versions of this check counted the wrong thing:

  * rows in `reports` — resumes analysed, not people — so a few busy
    recruiters closed sign-up for everyone;
  * `auth.admin.list_users()` — which is paginated and returns 50 users by
    default, so the count could never pass 50 and the ceiling never applied.

The count now comes from `profiles` (one row per account) as an exact count,
and the ceiling is configuration: MAX_REGISTERED_USERS, 0 for none.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.exceptions import CapacityLimitExceeded
from app.main import app

client = TestClient(app)
LIMIT = 5000


@pytest.fixture(autouse=True)
def fixed_limit(monkeypatch):
    monkeypatch.setattr(settings, "MAX_REGISTERED_USERS", LIMIT)


def _signup(email="newrecruiter@example.com"):
    return client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "New Recruiter"},
    )


def _db_with_profiles(count, fail=False):
    """A Supabase mock whose profiles table holds `count` accounts."""
    db = MagicMock()
    query = db.table.return_value.select.return_value.limit.return_value
    if fail:
        query.execute.side_effect = Exception("db down")
    else:
        query.execute.return_value = MagicMock(count=count, data=[])
    return db


@pytest.fixture
def override_db():
    def _use(db):
        app.dependency_overrides[get_db] = lambda: db

    yield _use
    app.dependency_overrides.clear()


def test_capacity_limit_exceeded_error_class():
    exc = CapacityLimitExceeded()
    assert exc.http_status == 429
    assert exc.code == "capacity_limit_exceeded"


def test_signup_blocked_at_the_user_limit(override_db):
    override_db(_db_with_profiles(LIMIT))
    res = _signup()
    assert res.status_code == 429
    assert res.json()["error"] == "capacity_limit_exceeded"


def test_signup_allowed_below_the_user_limit(override_db):
    override_db(_db_with_profiles(LIMIT - 1))
    assert _signup("under_limit@example.com").status_code != 429


def test_the_count_is_exact_not_a_page_of_users(override_db):
    """list_users() returned at most 50 — the ceiling could never trigger."""
    db = _db_with_profiles(LIMIT + 10)
    db.auth.admin.list_users.return_value = [object()] * 50
    override_db(db)
    assert _signup("paged@example.com").status_code == 429
    db.table.assert_any_call("profiles")
    db.table.return_value.select.assert_any_call("id", count="exact")


def test_a_zero_limit_means_no_ceiling(override_db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_REGISTERED_USERS", 0)
    override_db(_db_with_profiles(10_000_000))
    assert _signup("unlimited@example.com").status_code != 429


def test_signup_is_allowed_when_capacity_cannot_be_determined(override_db):
    """
    Capacity is a commercial guardrail, not a security control: an outage in
    the count must not close registration.
    """
    override_db(_db_with_profiles(0, fail=True))
    assert _signup("capacity_unknown@example.com").status_code != 429


def test_local_store_counts_persisted_users_not_just_in_memory(monkeypatch):
    """
    Without a DB the check used to count `_mem_users`, a process-local dict
    cleared on every restart — so the limit silently reset itself each deploy.
    """
    from app.api.v1.endpoints import auth as auth_ep

    monkeypatch.setattr(auth_ep.local_db, "count_users", lambda: LIMIT)
    assert _signup("local_limit@example.com").status_code == 429
