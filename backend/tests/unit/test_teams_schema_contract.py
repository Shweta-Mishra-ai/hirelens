"""
Regression test: public.team_members has a composite primary key
(team_id, user_id) and no `id` column at all (see
sql/002_team_collaboration.sql). A real Supabase/PostgREST insert
containing an unknown column is rejected outright — so an insert here
that includes "id" fails on every real database, even though the
try/except swallowed that failure and silently fell back to in-memory
storage, making the bug invisible until someone actually connected a
real database and looked for their team the next day.

This test doesn't hit a real Supabase — it uses a MagicMock in place of
the db client, which doesn't know or care about columns. Instead it
directly inspects the insert payload teams.py sends, and asserts it
only contains columns that actually exist on the table.
"""

from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user, get_db

client = TestClient(app)

# Matches sql/002_team_collaboration.sql exactly.
TEAM_MEMBERS_COLUMNS = {"team_id", "user_id", "role", "joined_at"}


def test_create_team_does_not_insert_unknown_columns_into_team_members():
    mock_db = MagicMock()
    captured_payloads = []

    def fake_table(name):
        m = MagicMock()
        if name == "team_members":
            def fake_insert(payload):
                captured_payloads.append(payload)
                return MagicMock(execute=MagicMock(return_value=MagicMock(data=[payload])))
            m.insert.side_effect = fake_insert
        else:
            m.insert.return_value.execute.return_value = MagicMock(
                data=[{"id": "team-1", "name": "Eng Hiring", "owner_id": "user-1"}]
            )
        return m

    mock_db.table.side_effect = fake_table

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1", "email": "a@b.com"}

    try:
        res = client.post("/api/v1/teams", json={"name": "Eng Hiring"})
        assert res.status_code == 200
    finally:
        app.dependency_overrides.clear()

    assert captured_payloads, "team_members insert was never called"
    payload_keys = set(captured_payloads[0].keys())
    assert payload_keys <= TEAM_MEMBERS_COLUMNS, (
        f"team_members insert included unknown column(s) "
        f"{payload_keys - TEAM_MEMBERS_COLUMNS} — a real Supabase insert "
        f"with these would be rejected by PostgREST"
    )
