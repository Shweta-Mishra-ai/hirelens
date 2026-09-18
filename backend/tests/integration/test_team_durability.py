"""
Team durability across a restart.

Teams, memberships and invites lived in process-local lists, so a team
created on a deployment without Supabase was gone on the next restart. That
took its membership with it, and left any report already shared to that team
pointing at a team_id that no longer resolved — so team-based access to a
report silently stopped working with no error anywhere.

Reports, comments, votes and co-pilot data were made durable earlier; this
was the last store that was not.

Clearing the in-process caches stands in for the restart: those lists are
exactly what a new process starts empty.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core import local_db
from app.core.security import decode_token
from app.main import app
from app.services.teams.access import _mem_team_invites, _mem_team_members, _mem_teams

client = TestClient(app)


def _user(tag="teamer"):
    email = f"{tag}_{uuid.uuid4().hex[:8]}@example.com"
    res = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": f"{tag.title()} Person"},
    )
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {
        "email": email,
        "headers": {"Authorization": f"Bearer {token}"},
        "id": decode_token(token)["sub"],
    }


def _restart():
    """A fresh process: every in-memory team cache starts empty."""
    _mem_teams.clear()
    _mem_team_members.clear()
    _mem_team_invites.clear()


@pytest.fixture
def owner():
    return _user("owner")


def _create_team(owner, name="Platform Hiring"):
    res = client.post("/api/v1/teams", headers=owner["headers"], json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()["id"]


class TestTeamsSurviveRestart:
    def test_team_is_still_listed(self, owner):
        _create_team(owner)
        _restart()
        teams = client.get("/api/v1/teams", headers=owner["headers"]).json()["teams"]
        assert [t["name"] for t in teams] == ["Platform Hiring"]

    def test_owner_role_is_preserved(self, owner):
        _create_team(owner)
        _restart()
        team = client.get("/api/v1/teams", headers=owner["headers"]).json()["teams"][0]
        assert team["my_role"] == "owner"

    def test_membership_is_preserved(self, owner):
        team_id = _create_team(owner)
        _restart()
        res = client.get(f"/api/v1/teams/{team_id}/members", headers=owner["headers"])
        assert res.status_code == 200
        members = res.json()["members"]
        assert [m["user_id"] for m in members] == [owner["id"]]
        assert members[0]["role"] == "owner"

    def test_members_are_named_not_ids(self, owner):
        team_id = _create_team(owner)
        _restart()
        members = client.get(f"/api/v1/teams/{team_id}/members", headers=owner["headers"]).json()["members"]
        assert members[0]["user_name"] == "You"

    def test_a_non_member_still_cannot_read_the_team(self, owner):
        team_id = _create_team(owner)
        _restart()
        stranger = _user("stranger")
        res = client.get(f"/api/v1/teams/{team_id}/members", headers=stranger["headers"])
        assert res.status_code == 403

    def test_teams_are_not_visible_to_other_users(self, owner):
        _create_team(owner)
        _restart()
        stranger = _user("stranger")
        assert client.get("/api/v1/teams", headers=stranger["headers"]).json()["teams"] == []


class TestInvitesSurviveRestart:
    def test_an_invite_sent_before_a_restart_can_still_be_accepted(self, owner):
        """
        The failure this pins: the invite existed only in memory, so a
        colleague who signed up after a redeploy joined nothing at all, with
        no error shown to anyone.
        """
        team_id = _create_team(owner)
        invitee_email = f"invitee_{uuid.uuid4().hex[:8]}@example.com"

        res = client.post(
            f"/api/v1/teams/{team_id}/invite",
            headers=owner["headers"],
            json={"email": invitee_email},
        )
        assert res.status_code == 200, res.text

        _restart()

        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": invitee_email, "password": "Password123!", "full_name": "Invited Person"},
        )
        assert signup.status_code == 200
        invitee_headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

        teams = client.get("/api/v1/teams", headers=invitee_headers).json()["teams"]
        assert [t["id"] for t in teams] == [team_id], "invite did not survive the restart"

    def test_accepting_an_invite_twice_does_not_duplicate_membership(self, owner):
        team_id = _create_team(owner)
        email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
        client.post(
            f"/api/v1/teams/{team_id}/invite", headers=owner["headers"], json={"email": email}
        )
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "Password123!", "full_name": "Dup Person"},
        )
        headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
        # Logging in again re-runs invite acceptance.
        client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})

        _restart()

        members = client.get(f"/api/v1/teams/{team_id}/members", headers=headers).json()["members"]
        user_ids = [m["user_id"] for m in members]
        assert len(user_ids) == len(set(user_ids)), f"duplicate memberships: {user_ids}"


class TestRemovalSurvivesRestart:
    def test_a_removed_member_does_not_come_back(self, owner):
        team_id = _create_team(owner)
        email = f"removed_{uuid.uuid4().hex[:8]}@example.com"
        client.post(
            f"/api/v1/teams/{team_id}/invite", headers=owner["headers"], json={"email": email}
        )
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "Password123!", "full_name": "Removed Person"},
        )
        member_id = decode_token(signup.json()["access_token"])["sub"]

        res = client.delete(
            f"/api/v1/teams/{team_id}/members/{member_id}", headers=owner["headers"]
        )
        assert res.status_code in (200, 204), res.text

        _restart()

        members = client.get(f"/api/v1/teams/{team_id}/members", headers=owner["headers"]).json()["members"]
        assert member_id not in [m["user_id"] for m in members]

    def test_a_removed_member_loses_access(self, owner):
        team_id = _create_team(owner)
        email = f"revoked_{uuid.uuid4().hex[:8]}@example.com"
        client.post(
            f"/api/v1/teams/{team_id}/invite", headers=owner["headers"], json={"email": email}
        )
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "Password123!", "full_name": "Revoked Person"},
        )
        token = signup.json()["access_token"]
        member_headers = {"Authorization": f"Bearer {token}"}
        member_id = decode_token(token)["sub"]

        assert client.get(f"/api/v1/teams/{team_id}/members", headers=member_headers).status_code == 200

        client.delete(f"/api/v1/teams/{team_id}/members/{member_id}", headers=owner["headers"])
        _restart()

        assert client.get(
            f"/api/v1/teams/{team_id}/members", headers=member_headers
        ).status_code == 403


class TestDeletionSurvivesRestart:
    """Deleting a team used to touch only the in-process caches, so the team
    and its whole roster were still on disk and came back on the next
    restart — and membership that outlives the team keeps every ex-member
    passing the access check for any report stamped with its id."""

    def test_a_deleted_team_does_not_come_back(self, owner):
        team_id = _create_team(owner, "Temporary Team")
        assert client.delete(f"/api/v1/teams/{team_id}", headers=owner["headers"]).status_code == 200

        _restart()

        teams = client.get("/api/v1/teams", headers=owner["headers"]).json()["teams"]
        assert team_id not in [t["id"] for t in teams]
        assert local_db.get_team_role(team_id, owner["id"]) is None

    def test_deleting_a_team_revokes_its_members(self, owner):
        team_id = _create_team(owner, "Doomed Team")
        member = _user("doomed_member")
        client.post(
            f"/api/v1/teams/{team_id}/invite", headers=owner["headers"], json={"email": member["email"]}
        )
        # Invites are accepted at signup, so re-signing in picks it up.
        joined = client.post(
            "/api/v1/auth/login", json={"email": member["email"], "password": "Password123!"}
        )
        member_headers = {"Authorization": f"Bearer {joined.json()['access_token']}"}

        client.delete(f"/api/v1/teams/{team_id}", headers=owner["headers"])
        _restart()

        assert local_db.get_team_role(team_id, member["id"]) is None
        assert client.get(
            f"/api/v1/teams/{team_id}/members", headers=member_headers
        ).status_code == 403

    def test_only_the_owner_can_delete(self, owner):
        team_id = _create_team(owner, "Guarded Team")
        stranger = _user("team_stranger")
        assert client.delete(f"/api/v1/teams/{team_id}", headers=stranger["headers"]).status_code == 403

        _restart()

        assert local_db.get_team_role(team_id, owner["id"]) == "owner"

    def test_the_local_delete_helper_is_owner_scoped(self):
        tid = str(uuid.uuid4())
        local_db.create_team(tid, "Owned Team", "user-a")
        local_db.add_team_member(tid, "user-b", "member")
        assert local_db.delete_team(tid, "user-b") is False
        assert local_db.get_team_role(tid, "user-a") == "owner"
        assert local_db.delete_team(tid, "user-a") is True
        assert local_db.get_team_role(tid, "user-a") is None
        assert local_db.get_team_role(tid, "user-b") is None


def test_local_db_team_helpers_are_owner_scoped():
    tid = str(uuid.uuid4())
    local_db.create_team(tid, "Direct Team", "user-a")
    assert local_db.get_team_role(tid, "user-a") == "owner"
    assert local_db.get_team_role(tid, "user-b") is None
    assert [t["id"] for t in local_db.list_teams_for_user("user-a")] == [tid]
    assert local_db.list_teams_for_user("user-b") == []
