"""
Registration capacity limit.

The check previously counted ROWS IN THE REPORTS TABLE — one row per resume
analysed, not one per user:

    db.table("reports").select("user_id", count="exact")

So five recruiters who had each analysed a thousand candidates would lock the
product to every new signup, while five thousand recruiters who had analysed
nothing would sail past it. These tests pin the metric to users.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.auth import MAX_RECRUITERS_CAPACITY
from app.core.dependencies import get_db
from app.core.exceptions import CapacityLimitExceeded
from app.main import app

client = TestClient(app)


def _signup(email="newrecruiter@example.com"):
    return client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "New Recruiter"},
    )


def _db_with_users(count):
    """A Supabase mock whose admin API reports `count` registered users."""
    db = MagicMock()
    db.auth.admin.list_users.return_value = [SimpleNamespace(id=str(i)) for i in range(count)]
    return db


@pytest.fixture
def override_db():
    created = {}

    def _use(db):
        created["db"] = db
        app.dependency_overrides[get_db] = lambda: db

    yield _use
    app.dependency_overrides.clear()


def test_capacity_limit_exceeded_error_class():
    exc = CapacityLimitExceeded()
    assert exc.http_status == 429
    assert exc.code == "capacity_limit_exceeded"
    assert "5,000" in exc.message


def test_signup_blocked_at_the_user_limit(override_db):
    override_db(_db_with_users(MAX_RECRUITERS_CAPACITY))
    res = _signup()
    assert res.status_code == 429
    body = res.json()
    assert body["error"] == "capacity_limit_exceeded"
    assert "5,000" in body["message"]


def test_signup_allowed_below_the_user_limit(override_db):
    override_db(_db_with_users(MAX_RECRUITERS_CAPACITY - 1))
    assert _signup("under_limit@example.com").status_code != 429


def test_report_volume_does_not_consume_capacity(override_db):
    """
    The regression that motivated this file: a handful of heavy users must
    not exhaust registration capacity. Two users with a million reports
    between them is still two users.
    """
    db = _db_with_users(2)
    # Make the reports table look enormous — it must be irrelevant.
    reports_result = MagicMock()
    reports_result.count = 1_000_000
    db.table.return_value.select.return_value.execute.return_value = reports_result

    override_db(db)
    assert _signup("heavy_usage@example.com").status_code != 429


def test_falls_back_to_profiles_when_admin_api_is_unavailable(override_db):
    """Not every Supabase deployment exposes the admin user list."""
    db = MagicMock()
    db.auth.admin.list_users.side_effect = Exception("not permitted")
    profiles_result = MagicMock()
    profiles_result.count = MAX_RECRUITERS_CAPACITY
    db.table.return_value.select.return_value.execute.return_value = profiles_result

    override_db(db)
    assert _signup("via_profiles@example.com").status_code == 429


def test_signup_is_allowed_when_capacity_cannot_be_determined(override_db):
    """
    Capacity is a commercial guardrail, not a security control. If neither
    source can be read, registration must stay open rather than failing shut
    on an unrelated outage.
    """
    db = MagicMock()
    db.auth.admin.list_users.side_effect = Exception("admin api down")
    db.table.return_value.select.return_value.execute.side_effect = Exception("db down")

    override_db(db)
    assert _signup("capacity_unknown@example.com").status_code != 429


def test_local_store_counts_persisted_users_not_just_in_memory(monkeypatch):
    """
    Without a DB the check used to count `_mem_users`, a process-local dict
    cleared on every restart — so the limit silently reset itself each deploy.
    """
    from app.api.v1.endpoints import auth as auth_ep

    monkeypatch.setattr(auth_ep.local_db, "count_users", lambda: MAX_RECRUITERS_CAPACITY)
    assert _signup("local_limit@example.com").status_code == 429
