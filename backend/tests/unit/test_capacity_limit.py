"""
Unit tests for 5,000 max user capacity limit enforcement & DB client reuse
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.exceptions import CapacityLimitExceeded
from app.core.dependencies import get_db

client = TestClient(app)


def test_capacity_limit_exceeded_error_class():
    exc = CapacityLimitExceeded()
    assert exc.http_status == 429
    assert exc.code == "capacity_limit_exceeded"
    assert "5,000" in exc.message


def test_signup_capacity_limit_enforced():
    # Capacity is now checked against distinct Supabase Auth users (via the
    # admin API), not `reports` rows — see _count_active_users(). Mock that
    # helper directly rather than the underlying paginated admin call.
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch(
            "app.api.v1.endpoints.auth._count_active_users", return_value=5000
        ):
            response = client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "newrecruiter@example.com",
                    "password": "Password123!",
                    "full_name": "New Recruiter",
                },
            )
        assert response.status_code == 429
        data = response.json()
        assert data["error"] == "capacity_limit_exceeded"
        assert "5,000" in data["message"]
    finally:
        app.dependency_overrides.clear()


def test_capacity_check_counts_distinct_users_not_reports():
    """
    Regression test: a single recruiter with many reports must not exhaust
    capacity for everyone else. _count_active_users should reflect distinct
    auth users (via the admin API), never the number of report rows.
    """
    from app.api.v1.endpoints.auth import _count_active_users

    mock_db = MagicMock()
    # One recruiter, 3000 reports — should NOT read as 3000 users.
    mock_db.auth.admin.list_users.side_effect = [
        [MagicMock() for _ in range(1)],  # single active user, first page
    ]
    count = _count_active_users(mock_db)
    assert count == 1


def test_db_client_reuse():
    import app.core.dependencies as deps
    deps._supabase_client = None

    with patch("app.core.config.settings.SUPABASE_URL", "https://example.supabase.co"), \
         patch("app.core.config.settings.SUPABASE_SERVICE_KEY", "secret-key-12345"), \
         patch("supabase.create_client") as mock_create:
        mock_inst = MagicMock()
        mock_create.return_value = mock_inst

        # First call creates client
        db1 = deps.get_db()
        assert db1 is mock_inst
        assert mock_create.call_count == 1

        # Second call reuses cached client
        db2 = deps.get_db()
        assert db2 is mock_inst
        assert mock_create.call_count == 1
