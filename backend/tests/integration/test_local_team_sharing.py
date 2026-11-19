"""
Team sharing on a deployment without Supabase (the local SQLite store).

Teams, invites, comments and votes already worked here, but sharing a report
with a team answered 503 — so a team could be built and joined and then had
nothing to look at. And on every deployment, a teammate had no way to find
a shared report: the dashboard lists your own uploads and the team page
listed people only. These tests hold the whole loop: share, find it on the
team, read it, discuss it, and the limits on what a teammate may do.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.analysis import _jobs
from app.core import local_db
from app.main import app

client = TestClient(app)


def _signup(name: str) -> dict:
    email = f"share-{uuid.uuid4().hex[:10]}@example.com"
    res = client.post("/api/v1/auth/signup", json={"email": email, "password": "Password123!", "full_name": name})
    assert res.status_code == 200, res.text
    body = res.json()
    return {"id": body["user"]["id"], "email": email, "name": name,
            "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _report(owner: dict, name: str = "Priya Sharma") -> str:
    rid = str(uuid.uuid4())
    assert local_db.save_report(
        rid, owner["id"], "cv.pdf", name, 81, "recommended",
        {"candidate": {"name": name, "email": "priya@example.com"}, "credibility": {"overall": 81}},
    )
    return rid


def _team(owner: dict, *members: dict) -> str:
    res = client.post("/api/v1/teams", headers=owner["headers"], json={"name": "Platform Hiring"})
    assert res.status_code == 200, res.text
    team_id = res.json()["id"]
    for m in members:
        assert local_db.add_team_member(team_id, m["id"], "member")
    return team_id


def _share(owner: dict, rid: str, team_id: str):
    return client.post(f"/api/v1/reports/{rid}/share", headers=owner["headers"], json={"team_id": team_id})


@pytest.fixture
def people():
    _jobs.clear()
    return _signup("Asha Owner"), _signup("Ben Mate"), _signup("Olu Outsider")


class TestSharing:
    def test_owner_shares_and_teammate_reads_it(self, people):
        owner, mate, outsider = people
        rid = _report(owner)
        team_id = _team(owner, mate)

        res = _share(owner, rid, team_id)
        assert res.status_code == 200, res.text
        assert res.json() == {"status": "shared", "team_id": team_id}

        mine = client.get(f"/api/v1/reports/{rid}", headers=owner["headers"]).json()
        assert mine["is_owner"] is True
        assert mine["team_id"] == team_id

        theirs = client.get(f"/api/v1/reports/{rid}", headers=mate["headers"])
        assert theirs.status_code == 200, theirs.text
        assert theirs.json()["is_owner"] is False
        assert theirs.json()["candidate"]["name"] == "Priya Sharma"
        assert "_owner_user_id" not in theirs.json()

        assert client.get(f"/api/v1/reports/{rid}", headers=outsider["headers"]).status_code in (403, 404)

    def test_reading_from_the_owners_cache_still_lets_a_teammate_in(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        team_id = _team(owner, mate)
        # The owner's read warms this process's in-memory copy, which knows
        # nothing about sharing; the teammate must not be refused because of it.
        client.get(f"/api/v1/reports/{rid}", headers=owner["headers"])
        assert _share(owner, rid, team_id).status_code == 200
        assert client.get(f"/api/v1/reports/{rid}", headers=mate["headers"]).status_code == 200

    def test_teammate_finds_it_on_the_team(self, people):
        owner, mate, outsider = people
        rid = _report(owner)
        _report(owner, "Not Shared")
        team_id = _team(owner, mate)
        _share(owner, rid, team_id)

        res = client.get(f"/api/v1/teams/{team_id}/reports", headers=mate["headers"])
        assert res.status_code == 200, res.text
        rows = res.json()["reports"]
        assert [r["id"] for r in rows] == [rid]
        assert rows[0]["candidate_name"] == "Priya Sharma"
        assert rows[0]["shared_by"] == "Asha Owner"
        assert rows[0]["is_mine"] is False

        own_view = client.get(f"/api/v1/teams/{team_id}/reports", headers=owner["headers"]).json()["reports"]
        assert own_view[0]["is_mine"] is True and own_view[0]["shared_by"] == "You"

        assert client.get(f"/api/v1/teams/{team_id}/reports", headers=outsider["headers"]).status_code == 403

    def test_teammate_discusses_and_uses_the_copilot(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        team_id = _team(owner, mate)
        _share(owner, rid, team_id)

        assert client.post(f"/api/v1/reports/{rid}/comments", headers=mate["headers"],
                           json={"comment": "Agree, onsite next"}).status_code in (200, 201)
        assert client.post(f"/api/v1/reports/{rid}/vote", headers=mate["headers"],
                           json={"vote": "advance"}).status_code in (200, 201)
        comments = client.get(f"/api/v1/reports/{rid}/comments", headers=owner["headers"]).json()
        assert any(c["comment"] == "Agree, onsite next" for c in comments.get("comments", comments))

        saved = client.post(f"/api/v1/reports/{rid}/copilot", headers=mate["headers"],
                            json={"scorecard": [], "custom_questions": [], "interview_notes": "Strong on SQL"})
        assert saved.status_code == 200, saved.text
        read = client.get(f"/api/v1/reports/{rid}/copilot", headers=owner["headers"]).json()
        assert read["copilot"]["interview_notes"] == "Strong on SQL"

    def test_teammate_cannot_take_the_owners_actions(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        team_id = _team(owner, mate)
        _share(owner, rid, team_id)

        assert client.post(f"/api/v1/reports/{rid}/decision", headers=mate["headers"],
                           json={"decision": "reject"}).status_code in (403, 404)
        draft = client.get(f"/api/v1/reports/{rid}/notify/draft?decision=reject", headers=mate["headers"])
        assert draft.status_code == 403
        assert "Only the person who added this candidate" in draft.json()["message"]
        sent = client.post(f"/api/v1/reports/{rid}/notify", headers=mate["headers"],
                           json={"decision": "reject", "subject": "Update", "body": "Not a match."})
        assert sent.status_code == 403
        assert _share(mate, rid, team_id).status_code == 403
        assert client.post(f"/api/v1/reports/{rid}/unshare", headers=mate["headers"]).status_code == 403
        assert client.delete(f"/api/v1/reports/{rid}", headers=mate["headers"]).status_code == 403
        # Still there, still shared.
        assert client.get(f"/api/v1/reports/{rid}", headers=mate["headers"]).status_code == 200

    def test_owner_can_draft_the_candidate_email(self, people):
        owner, _, _ = people
        rid = _report(owner)
        res = client.get(f"/api/v1/reports/{rid}/notify/draft?decision=advance", headers=owner["headers"])
        assert res.status_code == 200, res.text
        assert res.json()["candidate_email"] == "priya@example.com"

    def test_sharing_with_a_team_you_are_not_in_is_refused_not_a_server_error(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        others_team = _team(mate)
        res = _share(owner, rid, others_team)
        assert res.status_code == 403
        assert "member of the team" in res.json()["message"]


class TestStoppingSharing:
    def test_unshare_removes_teammate_access(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        team_id = _team(owner, mate)
        _share(owner, rid, team_id)

        assert client.post(f"/api/v1/reports/{rid}/unshare", headers=owner["headers"]).status_code == 200
        assert client.get(f"/api/v1/reports/{rid}", headers=mate["headers"]).status_code in (403, 404)
        assert client.get(f"/api/v1/teams/{team_id}/reports", headers=mate["headers"]).json()["reports"] == []

    def test_deleting_the_team_unshares_its_reports(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        team_id = _team(owner, mate)
        _share(owner, rid, team_id)

        assert client.delete(f"/api/v1/teams/{team_id}", headers=owner["headers"]).status_code in (200, 204)
        assert client.get(f"/api/v1/reports/{rid}", headers=mate["headers"]).status_code in (403, 404)
        assert client.get(f"/api/v1/reports/{rid}", headers=owner["headers"]).json()["team_id"] is None

    def test_a_resave_keeps_the_report_shared(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        team_id = _team(owner, mate)
        _share(owner, rid, team_id)
        # Verification and other updates rewrite the row with INSERT OR REPLACE.
        assert local_db.save_report(rid, owner["id"], "cv.pdf", "Priya Sharma", 70, "manual_review",
                                    {"candidate": {"name": "Priya Sharma"}})
        assert client.get(f"/api/v1/reports/{rid}", headers=mate["headers"]).status_code == 200


class TestDeletingAReport:
    def test_delete_takes_its_comments_and_votes(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        team_id = _team(owner, mate)
        _share(owner, rid, team_id)
        client.post(f"/api/v1/reports/{rid}/comments", headers=mate["headers"], json={"comment": "note"})
        client.post(f"/api/v1/reports/{rid}/vote", headers=mate["headers"], json={"vote": "maybe"})

        assert client.delete(f"/api/v1/reports/{rid}", headers=owner["headers"]).status_code == 204
        assert client.get(f"/api/v1/reports/{rid}", headers=owner["headers"]).status_code == 404
        with local_db._get_connection() as conn:
            for table in ("report_comments", "report_votes"):
                n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE report_id = ?", (rid,)).fetchone()[0]
                assert n == 0, table


class TestTheDiskCopyIsTheTruth:
    """
    The in-memory copy of a report is a per-process cache. Reading it ahead of
    the local store showed the owner a shared report as "not shared" (the
    cache predates the share), and verification kept its results only there,
    so a restart lost them.
    """

    def test_owner_sees_the_share_even_with_a_warm_cache(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        team_id = _team(owner, mate)
        client.get(f"/api/v1/reports/{rid}", headers=owner["headers"])  # warm any cache
        _jobs[f"report_{rid}"] = {**local_db.get_report(rid, owner["id"]), "team_id": None}
        _share(owner, rid, team_id)
        assert client.get(f"/api/v1/reports/{rid}", headers=owner["headers"]).json()["team_id"] == team_id

    def _verify(self, owner, rid):
        from unittest.mock import AsyncMock, patch

        empty = AsyncMock(return_value=[])
        with patch("app.api.v1.endpoints.verify.verify_github", new=AsyncMock(return_value={"status": "not_found", "note": "No such user"})), \
             patch("app.api.v1.endpoints.verify.verify_education", new=empty), \
             patch("app.api.v1.endpoints.verify.verify_certifications", new=empty), \
             patch("app.api.v1.endpoints.verify.verify_experience_companies", new=empty):
            return client.post(f"/api/v1/verify/{rid}/run", headers=owner["headers"], json={})

    def test_verification_runs_after_a_restart(self, people):
        owner, _, _ = people
        rid = _report(owner)
        _jobs.clear()  # a fresh process: nothing in memory
        res = self._verify(owner, rid)
        assert res.status_code == 200, res.text

    def test_verification_results_survive_a_restart(self, people):
        owner, _, _ = people
        rid = _report(owner)
        assert self._verify(owner, rid).status_code == 200
        _jobs.clear()
        report = client.get(f"/api/v1/reports/{rid}", headers=owner["headers"]).json()
        assert report["verification"]["github"]["status"] == "not_found"
        assert report["is_owner"] is True

    def test_a_teammate_cannot_run_verification(self, people):
        owner, mate, _ = people
        rid = _report(owner)
        team_id = _team(owner, mate)
        _share(owner, rid, team_id)
        assert self._verify(mate, rid).status_code in (403, 404)
