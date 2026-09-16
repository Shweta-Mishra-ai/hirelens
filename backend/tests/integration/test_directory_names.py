"""
Turning a user id into a person, on both deployments.

The earlier fix for raw UUIDs in the UI read names straight from the local
SQLite users table. On a Supabase deployment that table has no rows —
the users live in auth.users — so the fix never applied to the deployment
that actually runs in production: teammates showed as a neutral badge and
every candidate email went out signed with the recruiter's raw email
address. app/services/directory.py asks Supabase's profiles table first and
falls back to SQLite, and these check both halves.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.analysis import _jobs
from app.core.dependencies import get_db
from app.main import app
from app.services import directory
from app.services.queue import batch_store
from app.services.teams import access
from tests.fake_supabase import FakeSupabase

client = TestClient(app)


def signup(email, name):
    creds = {"email": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": name})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    payload = res.json()
    return {
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user_id": payload["user"]["id"],
        "email": email,
        "name": name,
    }


class TestTheResolver:
    def test_a_name_comes_from_the_profiles_table(self):
        db = FakeSupabase({"profiles": [
            {"id": "u1", "full_name": "Anita Rao", "email": "anita@example.com"},
        ]})
        assert directory.get_display_names(db, ["u1"])["u1"]["full_name"] == "Anita Rao"
        assert directory.get_display_name(db, "u1") == "Anita Rao"

    def test_several_ids_resolve_in_one_query(self):
        db = FakeSupabase({"profiles": [
            {"id": "u1", "full_name": "Anita Rao", "email": "a@example.com"},
            {"id": "u2", "full_name": "Bharat Shah", "email": "b@example.com"},
        ]})
        names = directory.get_display_names(db, ["u1", "u2", "u1"])
        assert {uid: p["full_name"] for uid, p in names.items()} == {
            "u1": "Anita Rao", "u2": "Bharat Shah",
        }
        assert len([c for c in db.calls if c == ("profiles", "select")]) == 1

    def test_an_id_with_no_profile_is_absent_rather_than_guessed(self):
        db = FakeSupabase({"profiles": []})
        assert directory.get_display_names(db, ["nobody"]) == {}

    def test_a_missing_name_falls_back_to_what_the_caller_chose(self):
        db = FakeSupabase({"profiles": []})
        assert directory.get_display_name(db, "nobody", "The Hiring Team") == "The Hiring Team"

    def test_a_blank_name_in_the_profile_does_not_win(self):
        db = FakeSupabase({"profiles": [{"id": "u1", "full_name": "   ", "email": "a@example.com"}]})
        assert directory.get_display_name(db, "u1", "fallback") == "fallback"

    def test_a_broken_profiles_table_falls_back_instead_of_erroring(self):
        db = FakeSupabase({"profiles": []})
        db.fail("profiles", "select")
        assert directory.get_display_names(db, ["u1"]) == {}
        assert directory.get_display_name(db, "u1", "The Hiring Team") == "The Hiring Team"

    def test_the_local_store_answers_when_there_is_no_supabase(self, fresh_local_db):
        user = fresh_local_db.create_user("local@example.com", "Password123!", "Local Person")
        assert directory.get_display_name(None, user["id"]) == "Local Person"

    def test_supabase_wins_over_a_stale_local_row(self, fresh_local_db):
        user = fresh_local_db.create_user("dual@example.com", "Password123!", "Old Name")
        db = FakeSupabase({"profiles": [{"id": user["id"], "full_name": "New Name", "email": "dual@example.com"}]})
        assert directory.get_display_name(db, user["id"]) == "New Name"

    def test_no_ids_means_no_query(self):
        db = FakeSupabase({"profiles": []})
        assert directory.get_display_names(db, []) == {}
        assert directory.get_display_names(db, [None, ""]) == {}
        assert db.calls == []


class TestNamesInTheUi:
    @pytest.fixture
    def owner(self):
        return signup("dir_owner@example.com", "Owner Olsen")

    @pytest.fixture
    def member(self):
        return signup("dir_member@example.com", "Mem Ber")

    @pytest.fixture
    def db(self, owner, member):
        """A real Supabase deployment, reproduced honestly.

        There, users live in auth.users and the local SQLite users table has
        no row for any of them — which is the whole reason the old
        SQLite-only lookup silently stopped working in production. So the
        signup rows are deleted here: if a name still appears, it can only
        have come from the profiles table.
        """
        from app.core import local_db as _local_db

        with _local_db._get_connection() as conn:
            conn.execute(
                "DELETE FROM users WHERE id IN (?, ?)", (owner["user_id"], member["user_id"])
            )
            conn.commit()
        assert _local_db.get_display_names([owner["user_id"], member["user_id"]]) == {}

        fake = FakeSupabase({
            "profiles": [
                {"id": owner["user_id"], "full_name": "Owner Olsen", "email": owner["email"]},
                {"id": member["user_id"], "full_name": "Mem Ber", "email": member["email"]},
            ],
            "teams": [{"id": "t1", "name": "Platform Hiring", "owner_id": owner["user_id"]}],
            "team_members": [
                {"id": "m1", "team_id": "t1", "user_id": owner["user_id"], "role": "owner",
                 "joined_at": "2026-01-01T00:00:00+00:00"},
                {"id": "m2", "team_id": "t1", "user_id": member["user_id"], "role": "member",
                 "joined_at": "2026-01-02T00:00:00+00:00"},
            ],
            "team_invites": [],
            "reports": [{"id": "rep1", "user_id": owner["user_id"], "team_id": "t1",
                         "candidate_name": "Anita Rao"}],
            "report_comments": [],
            "report_votes": [],
        })
        app.dependency_overrides[get_db] = lambda: fake
        access._mem_teams.clear()
        access._mem_team_members.clear()
        access._mem_team_invites.clear()
        yield fake
        app.dependency_overrides.pop(get_db, None)

    def test_the_team_roster_shows_names(self, owner, member, db):
        rows = client.get("/api/v1/teams/t1/members", headers=member["headers"]).json()["members"]
        by_id = {r["user_id"]: r for r in rows}
        assert by_id[owner["user_id"]]["user_name"] == "Owner Olsen"
        assert by_id[member["user_id"]]["user_name"] == "You"

    def test_a_comment_is_attributed_to_a_person(self, owner, member, db):
        client.post("/api/v1/reports/rep1/comments", headers=member["headers"],
                    json={"comment": "Second opinion"})
        listed = client.get("/api/v1/reports/rep1/comments", headers=owner["headers"]).json()
        row = listed["comments"][0]
        assert row["user_name"] == "Mem Ber"
        assert row["is_me"] is False

    def test_a_vote_is_attributed_to_a_person(self, owner, member, db):
        client.post("/api/v1/reports/rep1/vote", headers=member["headers"], json={"vote": "advance"})
        body = client.get("/api/v1/reports/rep1/votes", headers=owner["headers"]).json()
        assert [v["user_name"] for v in body["votes"]] == ["Mem Ber"]

    def test_an_invite_email_names_the_inviter(self, owner, db, monkeypatch):
        sent = []

        async def fake_invite(to_email, team_name, inviter_name, invite_url):
            sent.append({"by": inviter_name, "team": team_name})
            return True

        import app.services.email.sender as sender
        monkeypatch.setattr(sender, "send_team_invite_email", fake_invite)

        client.post("/api/v1/teams/t1/invite", headers=owner["headers"],
                    json={"email": "new@example.com"})
        assert sent[0]["by"] == "Owner Olsen"
        assert "@" not in sent[0]["by"]

    def test_a_candidate_email_is_signed_with_a_name(self, owner, db, monkeypatch):
        sent = []

        async def fake_send(to_email, subject, body):
            sent.append(body)
            return True

        import app.services.email.sender as sender
        monkeypatch.setattr(sender, "send_candidate_decision_email", fake_send)

        uid = owner["user_id"]
        _jobs["report_rb"] = {
            "candidate": {"name": "Anita Rao", "email": "anita@example.com"},
            "credibility": {"overall": 80, "recommendation": "recommended"},
            "_owner_user_id": uid,
        }
        _jobs["jb"] = {
            "id": "jb", "user_id": uid, "batch_id": "bn", "status": "complete",
            "stage": "complete", "progress": 100, "file_name": "a.pdf",
            "report_id": "rb", "error": None,
        }
        batch_store.create_batch(None, "bn", uid, ["jb"], total=1)

        res = client.post("/api/v1/bulk/bn/notify-all", headers=owner["headers"],
                          json={"decision": "advance"})
        assert res.status_code == 200, res.text
        assert "Owner Olsen" in sent[0]
        assert owner["email"] not in sent[0]
