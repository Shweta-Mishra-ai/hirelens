"""
The Discuss tab on the Supabase path.

test_collaboration_local.py covers the SQLite fallback. This file covers
the other half — the one a deployed instance runs — including the parts
that only exist there: sharing a report with a team, and a teammate who is
not the owner reading, commenting and voting on it.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db
from app.main import app
from tests.fake_supabase import FakeSupabase

client = TestClient(app)


def signup(email: str, name: str):
    creds = {"email": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": name})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    payload = res.json()
    return {
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user_id": payload["user"]["id"],
        "name": name,
    }


@pytest.fixture
def owner():
    return signup("collab_owner@example.com", "Owner Olsen")


@pytest.fixture
def teammate():
    return signup("collab_mate@example.com", "Mate Mehra")


@pytest.fixture
def outsider():
    return signup("collab_outsider@example.com", "Out Sider")


@pytest.fixture
def db(owner, teammate):
    fake = FakeSupabase({
        "reports": [{
            "id": "rep1",
            "user_id": owner["user_id"],
            "team_id": None,
            "candidate_name": "Anita Rao",
        }],
        "team_members": [
            {"team_id": "t1", "user_id": owner["user_id"], "role": "owner"},
            {"team_id": "t1", "user_id": teammate["user_id"], "role": "member"},
        ],
        "report_comments": [],
        "report_votes": [],
    })
    app.dependency_overrides[get_db] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_db, None)


def share(db):
    db.tables["reports"][0]["team_id"] = "t1"


class TestSharing:
    def test_the_owner_can_share_with_a_team_they_belong_to(self, owner, db):
        res = client.post("/api/v1/reports/rep1/share", headers=owner["headers"], json={"team_id": "t1"})
        assert res.status_code == 200, res.text
        assert db.tables["reports"][0]["team_id"] == "t1"

    def test_sharing_with_a_team_you_are_not_in_is_refused(self, owner, db):
        res = client.post("/api/v1/reports/rep1/share", headers=owner["headers"], json={"team_id": "t-other"})
        assert res.status_code >= 400
        assert db.tables["reports"][0]["team_id"] is None

    def test_only_the_owner_can_share(self, teammate, db):
        res = client.post("/api/v1/reports/rep1/share", headers=teammate["headers"], json={"team_id": "t1"})
        assert res.status_code == 403

    def test_unsharing_puts_it_back(self, owner, db):
        client.post("/api/v1/reports/rep1/share", headers=owner["headers"], json={"team_id": "t1"})
        res = client.post("/api/v1/reports/rep1/unshare", headers=owner["headers"])
        assert res.status_code == 200, res.text
        assert db.tables["reports"][0]["team_id"] is None

    def test_only_the_owner_can_unshare(self, teammate, db):
        share(db)
        res = client.post("/api/v1/reports/rep1/unshare", headers=teammate["headers"])
        assert res.status_code == 403

    def test_sharing_an_unknown_report_is_a_404(self, owner, db):
        res = client.post("/api/v1/reports/nope/share", headers=owner["headers"], json={"team_id": "t1"})
        assert res.status_code == 404


class TestComments:
    def test_the_owner_can_comment_and_read_it_back(self, owner, db):
        res = client.post(
            "/api/v1/reports/rep1/comments", headers=owner["headers"], json={"comment": "Strong systems answer"}
        )
        assert res.status_code == 200, res.text
        listed = client.get("/api/v1/reports/rep1/comments", headers=owner["headers"]).json()
        assert [c["comment"] for c in listed["comments"]] == ["Strong systems answer"]

    def test_a_comment_is_labelled_with_a_name_not_a_user_id(self, owner, teammate, db):
        share(db)
        client.post("/api/v1/reports/rep1/comments", headers=teammate["headers"], json={"comment": "Agreed"})
        listed = client.get("/api/v1/reports/rep1/comments", headers=owner["headers"]).json()
        row = listed["comments"][0]
        assert row["user_name"] == "Mate Mehra"
        assert row["is_me"] is False
        assert teammate["user_id"] not in str(row.get("user_name"))

    def test_your_own_comment_reads_as_yours(self, owner, db):
        client.post("/api/v1/reports/rep1/comments", headers=owner["headers"], json={"comment": "Mine"})
        listed = client.get("/api/v1/reports/rep1/comments", headers=owner["headers"]).json()
        assert listed["comments"][0]["user_name"] == "You"
        assert listed["comments"][0]["is_me"] is True

    def test_a_teammate_can_comment_on_a_shared_report(self, teammate, db):
        share(db)
        res = client.post(
            "/api/v1/reports/rep1/comments", headers=teammate["headers"], json={"comment": "Second opinion"}
        )
        assert res.status_code == 200, res.text

    def test_an_outsider_cannot_read_or_comment(self, outsider, db):
        share(db)
        assert client.get("/api/v1/reports/rep1/comments", headers=outsider["headers"]).status_code == 403
        assert client.post(
            "/api/v1/reports/rep1/comments", headers=outsider["headers"], json={"comment": "hi"}
        ).status_code == 403

    def test_an_unshared_report_is_private_again(self, teammate, db):
        """Unsharing has to actually close the door, not just hide the tab."""
        assert client.get("/api/v1/reports/rep1/comments", headers=teammate["headers"]).status_code == 403

    def test_an_empty_comment_is_rejected(self, owner, db):
        res = client.post("/api/v1/reports/rep1/comments", headers=owner["headers"], json={"comment": "   "})
        assert res.status_code == 422

    def test_the_author_can_delete_their_comment(self, owner, db):
        created = client.post(
            "/api/v1/reports/rep1/comments", headers=owner["headers"], json={"comment": "Oops"}
        ).json()
        res = client.delete(f"/api/v1/reports/rep1/comments/{created['id']}", headers=owner["headers"])
        assert res.status_code == 200, res.text
        assert db.tables["report_comments"] == []

    def test_you_cannot_delete_someone_else_s_comment(self, owner, teammate, db):
        share(db)
        created = client.post(
            "/api/v1/reports/rep1/comments", headers=teammate["headers"], json={"comment": "Theirs"}
        ).json()
        res = client.delete(f"/api/v1/reports/rep1/comments/{created['id']}", headers=owner["headers"])
        assert res.status_code == 403
        assert len(db.tables["report_comments"]) == 1

    def test_deleting_an_unknown_comment_is_a_404(self, owner, db):
        res = client.delete("/api/v1/reports/rep1/comments/nope", headers=owner["headers"])
        assert res.status_code == 404

    def test_a_listing_failure_degrades_to_empty_rather_than_erroring(self, owner, db):
        db.fail("report_comments", "select")
        res = client.get("/api/v1/reports/rep1/comments", headers=owner["headers"])
        assert res.status_code == 200
        assert res.json()["comments"] == []

    def test_a_failed_write_is_not_reported_as_posted(self, owner, db):
        db.fail("report_comments", "insert")
        res = client.post("/api/v1/reports/rep1/comments", headers=owner["headers"], json={"comment": "x"})
        assert res.status_code >= 400


class TestVotes:
    def test_a_vote_is_counted_and_read_back(self, owner, db):
        res = client.post("/api/v1/reports/rep1/vote", headers=owner["headers"], json={"vote": "advance"})
        assert res.status_code == 200, res.text
        body = client.get("/api/v1/reports/rep1/votes", headers=owner["headers"]).json()
        assert body["tally"] == {"advance": 1, "reject": 0, "maybe": 0}
        assert body["my_vote"] == "advance"

    def test_changing_your_mind_replaces_your_vote_rather_than_adding_one(self, owner, db):
        client.post("/api/v1/reports/rep1/vote", headers=owner["headers"], json={"vote": "advance"})
        client.post("/api/v1/reports/rep1/vote", headers=owner["headers"], json={"vote": "reject"})
        body = client.get("/api/v1/reports/rep1/votes", headers=owner["headers"]).json()
        assert body["tally"] == {"advance": 0, "reject": 1, "maybe": 0}
        assert body["my_vote"] == "reject"

    def test_two_people_on_a_shared_report_both_count(self, owner, teammate, db):
        share(db)
        client.post("/api/v1/reports/rep1/vote", headers=owner["headers"], json={"vote": "advance"})
        client.post("/api/v1/reports/rep1/vote", headers=teammate["headers"], json={"vote": "maybe"})
        body = client.get("/api/v1/reports/rep1/votes", headers=owner["headers"]).json()
        assert body["tally"] == {"advance": 1, "reject": 0, "maybe": 1}
        assert body["my_vote"] == "advance"

    def test_an_outsider_cannot_vote(self, outsider, db):
        share(db)
        res = client.post("/api/v1/reports/rep1/vote", headers=outsider["headers"], json={"vote": "advance"})
        assert res.status_code == 403

    def test_an_unknown_vote_value_is_rejected(self, owner, db):
        res = client.post("/api/v1/reports/rep1/vote", headers=owner["headers"], json={"vote": "shrug"})
        assert res.status_code == 422

    def test_a_failed_vote_write_is_not_reported_as_recorded(self, owner, db):
        db.fail("report_votes", "upsert")
        res = client.post("/api/v1/reports/rep1/vote", headers=owner["headers"], json={"vote": "advance"})
        assert res.status_code >= 400

    def test_a_tally_lookup_failure_degrades_rather_than_erroring(self, owner, db):
        db.fail("report_votes", "select")
        body = client.get("/api/v1/reports/rep1/votes", headers=owner["headers"]).json()
        assert body["tally"] == {"advance": 0, "reject": 0, "maybe": 0}
        assert body["my_vote"] is None


class TestWithoutSupabase:
    """Sharing needs the shared database; the rest of the tab must not."""

    def test_sharing_says_why_it_cannot_work(self, owner):
        res = client.post("/api/v1/reports/any/share", headers=owner["headers"], json={"team_id": "t1"})
        assert res.status_code == 503
        assert "database" in res.json()["message"].lower()
        assert "comments and votes still work" in res.json()["message"].lower()
