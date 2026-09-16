"""
Teams on the Supabase path.

test_team_durability.py covers the SQLite fallback (and the restart case
that motivated it). This covers the branch a deployed instance runs, plus
the two authorization rules that were previously silent no-ops: removing a
member and deleting a team both used to rebind a module-level name instead
of mutating the shared list, so the access checks in access.py never saw
the change and a removed member kept their access for the life of the
process.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db
from app.main import app
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


@pytest.fixture
def owner():
    return signup("teams_owner@example.com", "Owner Olsen")


@pytest.fixture
def member():
    return signup("teams_member@example.com", "Mem Ber")


@pytest.fixture
def outsider():
    return signup("teams_outsider@example.com", "Out Sider")


@pytest.fixture
def db(owner, member):
    fake = FakeSupabase({
        "teams": [{"id": "t1", "name": "Platform Hiring", "owner_id": owner["user_id"]}],
        "team_members": [
            {"team_id": "t1", "user_id": owner["user_id"], "role": "owner",
             "joined_at": "2026-01-01T00:00:00+00:00"},
            {"team_id": "t1", "user_id": member["user_id"], "role": "member",
             "joined_at": "2026-01-02T00:00:00+00:00"},
        ],
        "team_invites": [],
    })
    app.dependency_overrides[get_db] = lambda: fake
    # access.py keeps a per-process cache that would otherwise answer
    # membership questions this test never set up.
    access._mem_teams.clear()
    access._mem_team_members.clear()
    access._mem_team_invites.clear()
    yield fake
    app.dependency_overrides.pop(get_db, None)
    access._mem_teams.clear()
    access._mem_team_members.clear()
    access._mem_team_invites.clear()


@pytest.fixture
def mailer(monkeypatch):
    sent = []

    async def fake_invite(to_email, team_name, inviter_name, invite_url):
        sent.append({"to": to_email, "team": team_name, "by": inviter_name, "url": invite_url})
        return True

    import app.api.v1.endpoints.teams as teams_ep
    import app.services.email.sender as sender
    monkeypatch.setattr(sender, "send_team_invite_email", fake_invite)
    return sent


class TestCreateAndList:
    def test_creating_a_team_makes_you_its_owner(self, owner, db):
        res = client.post("/api/v1/teams", headers=owner["headers"], json={"name": "Design Hiring"})
        assert res.status_code == 200, res.text
        team_id = res.json()["id"]
        members = db.tables["team_members"]
        mine = next(m for m in members if m["team_id"] == team_id)
        assert mine["user_id"] == owner["user_id"]
        assert mine["role"] == "owner"

    def test_creating_a_team_writes_a_membership_row_supabase_accepts(self, owner, db):
        """team_members is keyed on (team_id, user_id) and has no id column.
        The insert used to send one anyway, so PostgREST refused it, the
        endpoint swallowed the error, and the team ended up in Supabase with
        its owner holding no membership at all."""
        before = len(db.tables["team_members"])
        res = client.post("/api/v1/teams", headers=owner["headers"], json={"name": "Design Hiring"})
        assert res.status_code == 200, res.text
        team_id = res.json()["id"]

        assert len(db.tables["team_members"]) == before + 1
        row = next(m for m in db.tables["team_members"] if m["team_id"] == team_id)
        assert row["user_id"] == owner["user_id"]
        assert row["role"] == "owner"

        # And the owner can immediately do owner-only things through Supabase.
        assert client.get(f"/api/v1/teams/{team_id}/members", headers=owner["headers"]).status_code == 200
        assert client.delete(f"/api/v1/teams/{team_id}", headers=owner["headers"]).status_code == 200

    def test_listing_shows_the_teams_you_belong_to_with_your_role(self, owner, member, db):
        owner_teams = client.get("/api/v1/teams", headers=owner["headers"]).json()["teams"]
        member_teams = client.get("/api/v1/teams", headers=member["headers"]).json()["teams"]
        assert [t["id"] for t in owner_teams] == ["t1"]
        assert owner_teams[0]["my_role"] == "owner"
        assert member_teams[0]["my_role"] == "member"

    def test_someone_in_no_teams_sees_an_empty_list(self, outsider, db):
        assert client.get("/api/v1/teams", headers=outsider["headers"]).json()["teams"] == []

    def test_a_nameless_team_is_rejected(self, owner, db):
        assert client.post("/api/v1/teams", headers=owner["headers"], json={"name": "  "}).status_code == 422


class TestMembers:
    def test_a_member_can_see_the_roster_by_name(self, member, owner, db):
        res = client.get("/api/v1/teams/t1/members", headers=member["headers"])
        assert res.status_code == 200, res.text
        rows = res.json()["members"]
        names = {r.get("user_name") for r in rows}
        assert "You" in names
        assert "Owner Olsen" in names
        for row in rows:
            assert row.get("user_name") != row.get("user_id")

    def test_an_outsider_cannot_see_the_roster(self, outsider, db):
        assert client.get("/api/v1/teams/t1/members", headers=outsider["headers"]).status_code == 403


class TestInvites:
    def test_an_owner_can_invite_and_the_invite_is_recorded(self, owner, db, mailer):
        res = client.post(
            "/api/v1/teams/t1/invite", headers=owner["headers"], json={"email": "new@example.com"}
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "invited"
        assert body["email_sent"] is True
        assert "invite_email=new@example.com" in body["invite_url"]
        assert any(i["email"] == "new@example.com" for i in db.tables["team_invites"])

    def test_the_invite_email_names_the_team_and_the_inviter(self, owner, db, mailer):
        client.post("/api/v1/teams/t1/invite", headers=owner["headers"], json={"email": "new@example.com"})
        assert mailer[0]["team"] == "Platform Hiring"
        assert mailer[0]["by"] == "Owner Olsen"  # the name, not the raw email address

    def test_inviting_the_same_person_twice_does_not_create_a_second_invite(self, owner, db, mailer):
        client.post("/api/v1/teams/t1/invite", headers=owner["headers"], json={"email": "new@example.com"})
        second = client.post(
            "/api/v1/teams/t1/invite", headers=owner["headers"], json={"email": "new@example.com"}
        )
        assert second.json()["status"] == "already_invited"
        assert len([i for i in db.tables["team_invites"] if i["email"] == "new@example.com"]) == 1

    def test_a_plain_member_cannot_invite(self, member, db, mailer):
        res = client.post(
            "/api/v1/teams/t1/invite", headers=member["headers"], json={"email": "new@example.com"}
        )
        assert res.status_code == 403
        assert mailer == []

    def test_an_outsider_cannot_invite(self, outsider, db, mailer):
        res = client.post(
            "/api/v1/teams/t1/invite", headers=outsider["headers"], json={"email": "new@example.com"}
        )
        assert res.status_code == 403
        assert mailer == []

    def test_a_malformed_address_is_rejected(self, owner, db, mailer):
        res = client.post("/api/v1/teams/t1/invite", headers=owner["headers"], json={"email": "not-an-email"})
        assert res.status_code == 422
        assert mailer == []


class TestRemoval:
    def test_removing_a_member_actually_revokes_their_access(self, owner, member, db):
        """The point of this test: the removal used to rebind a module-level
        name rather than mutate the shared list, so the authorization check
        kept saying yes."""
        assert client.get("/api/v1/teams/t1/members", headers=member["headers"]).status_code == 200

        res = client.delete(f"/api/v1/teams/t1/members/{member['user_id']}", headers=owner["headers"])
        assert res.status_code == 200, res.text
        assert not any(m["user_id"] == member["user_id"] for m in db.tables["team_members"])
        assert client.get("/api/v1/teams/t1/members", headers=member["headers"]).status_code == 403

    def test_the_owner_cannot_be_removed(self, owner, db):
        res = client.delete(f"/api/v1/teams/t1/members/{owner['user_id']}", headers=owner["headers"])
        assert res.status_code >= 400
        assert any(m["role"] == "owner" for m in db.tables["team_members"])

    def test_a_plain_member_cannot_remove_anyone(self, owner, member, db):
        res = client.delete(f"/api/v1/teams/t1/members/{owner['user_id']}", headers=member["headers"])
        assert res.status_code == 403

    def test_an_outsider_cannot_remove_anyone(self, outsider, member, db):
        res = client.delete(f"/api/v1/teams/t1/members/{member['user_id']}", headers=outsider["headers"])
        assert res.status_code == 403
        assert any(m["user_id"] == member["user_id"] for m in db.tables["team_members"])


class TestDeletion:
    def test_the_owner_can_delete_the_team(self, owner, db):
        res = client.delete("/api/v1/teams/t1", headers=owner["headers"])
        assert res.status_code == 200, res.text
        assert db.tables["teams"] == []

    def test_a_deleted_team_is_no_longer_reachable(self, owner, member, db):
        client.delete("/api/v1/teams/t1", headers=owner["headers"])
        assert client.get("/api/v1/teams/t1/members", headers=member["headers"]).status_code == 403

    def test_a_member_cannot_delete_the_team(self, member, db):
        assert client.delete("/api/v1/teams/t1", headers=member["headers"]).status_code == 403
        assert db.tables["teams"] != []

    def test_an_outsider_cannot_delete_the_team(self, outsider, db):
        assert client.delete("/api/v1/teams/t1", headers=outsider["headers"]).status_code == 403
