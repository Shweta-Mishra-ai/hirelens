"""
Collaboration without Supabase, and co-pilot access control.

Two problems this covers.

1. Every collaboration endpoint raised DBRequiredError the moment `db` was
   falsy, so comments, votes and sharing returned 503 and the whole Discuss
   tab was dead on any deployment without Supabase — a documented feature
   failing entirely rather than degrading.

2. SECURITY: co-pilot data was held in a module-level dict keyed by report id
   with no owner in the key. The GET path fell through to that dict with no
   ownership check at all, and the POST path wrote to it before any check, so
   any authenticated user could read and overwrite another recruiter's
   private interview notes — which routinely contain compensation
   expectations and candid assessments.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.analysis import _jobs, _persist_report_locally, _stamp_report_metadata
from app.core.security import decode_token
from app.main import app

client = TestClient(app)


def _user(tag):
    email = f"{tag}_{uuid.uuid4().hex[:8]}@example.com"
    res = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": tag.title()},
    )
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {
        "headers": {"Authorization": f"Bearer {token}"},
        "id": decode_token(token)["sub"],
    }


def _report_for(user):
    rid = str(uuid.uuid4())
    blob = {
        "candidate": {"name": "Priya Raghavan"},
        "credibility": {"overall": 74, "recommendation": "manual_review", "sub_scores": {}},
        "flags": [],
        "summary": "s",
    }
    _stamp_report_metadata(blob, user_id=user["id"], filename="cv.pdf", report_id=rid)
    _persist_report_locally(blob, report_id=rid, user_id=user["id"], filename="cv.pdf")
    _jobs[f"report_{rid}"] = blob
    return rid


@pytest.fixture
def owner():
    return _user("owner")


@pytest.fixture
def stranger():
    return _user("stranger")


class TestCommentsWithoutSupabase:
    def test_posting_a_comment_works(self, owner):
        rid = _report_for(owner)
        res = client.post(
            f"/api/v1/reports/{rid}/comments",
            headers=owner["headers"],
            json={"comment": "Checked the ledger claim — it holds up."},
        )
        assert res.status_code == 200, res.text
        assert res.json()["comment"].startswith("Checked the ledger")

    def test_comment_is_listed_afterwards(self, owner):
        rid = _report_for(owner)
        client.post(
            f"/api/v1/reports/{rid}/comments",
            headers=owner["headers"],
            json={"comment": "First note"},
        )
        body = client.get(f"/api/v1/reports/{rid}/comments", headers=owner["headers"]).json()
        assert [c["comment"] for c in body["comments"]] == ["First note"]

    def test_comment_survives_a_restart(self, owner):
        rid = _report_for(owner)
        client.post(
            f"/api/v1/reports/{rid}/comments",
            headers=owner["headers"],
            json={"comment": "Durable note"},
        )
        _jobs.clear()  # stands in for the process restarting
        body = client.get(f"/api/v1/reports/{rid}/comments", headers=owner["headers"]).json()
        assert any(c["comment"] == "Durable note" for c in body["comments"])

    def test_author_can_delete_their_comment(self, owner):
        rid = _report_for(owner)
        cid = client.post(
            f"/api/v1/reports/{rid}/comments",
            headers=owner["headers"],
            json={"comment": "Delete me"},
        ).json()["id"]
        assert client.delete(
            f"/api/v1/reports/{rid}/comments/{cid}", headers=owner["headers"]
        ).status_code == 200
        body = client.get(f"/api/v1/reports/{rid}/comments", headers=owner["headers"]).json()
        assert body["comments"] == []

    def test_a_stranger_cannot_delete_someone_elses_comment(self, owner, stranger):
        rid = _report_for(owner)
        cid = client.post(
            f"/api/v1/reports/{rid}/comments",
            headers=owner["headers"],
            json={"comment": "Mine"},
        ).json()["id"]
        res = client.delete(f"/api/v1/reports/{rid}/comments/{cid}", headers=stranger["headers"])
        assert res.status_code in (403, 404)
        body = client.get(f"/api/v1/reports/{rid}/comments", headers=owner["headers"]).json()
        assert len(body["comments"]) == 1, "comment was deleted by a non-author"

    def test_a_stranger_cannot_read_comments_on_a_report_they_cannot_see(self, owner, stranger):
        rid = _report_for(owner)
        client.post(
            f"/api/v1/reports/{rid}/comments",
            headers=owner["headers"],
            json={"comment": "Confidential"},
        )
        res = client.get(f"/api/v1/reports/{rid}/comments", headers=stranger["headers"])
        assert res.status_code in (403, 404)
        assert "Confidential" not in res.text

    def test_blank_comment_is_rejected(self, owner):
        rid = _report_for(owner)
        res = client.post(
            f"/api/v1/reports/{rid}/comments", headers=owner["headers"], json={"comment": "   "}
        )
        assert res.status_code == 422


class TestVotesWithoutSupabase:
    def test_casting_and_tallying_a_vote(self, owner):
        rid = _report_for(owner)
        assert client.post(
            f"/api/v1/reports/{rid}/vote", headers=owner["headers"], json={"vote": "advance"}
        ).status_code == 200

        body = client.get(f"/api/v1/reports/{rid}/votes", headers=owner["headers"]).json()
        assert body["tally"]["advance"] == 1
        assert body["my_vote"] == "advance"

    def test_revoting_replaces_rather_than_adds(self, owner):
        rid = _report_for(owner)
        for vote in ("advance", "maybe", "reject"):
            client.post(f"/api/v1/reports/{rid}/vote", headers=owner["headers"], json={"vote": vote})

        body = client.get(f"/api/v1/reports/{rid}/votes", headers=owner["headers"]).json()
        assert sum(body["tally"].values()) == 1, "re-voting must not stack votes"
        assert body["my_vote"] == "reject"

    def test_vote_survives_a_restart(self, owner):
        rid = _report_for(owner)
        client.post(f"/api/v1/reports/{rid}/vote", headers=owner["headers"], json={"vote": "maybe"})
        _jobs.clear()
        body = client.get(f"/api/v1/reports/{rid}/votes", headers=owner["headers"]).json()
        assert body["my_vote"] == "maybe"

    def test_an_invalid_vote_is_rejected(self, owner):
        rid = _report_for(owner)
        res = client.post(
            f"/api/v1/reports/{rid}/vote", headers=owner["headers"], json={"vote": "hire_immediately"}
        )
        assert res.status_code == 422


class TestSharingExplainsItself:
    def test_team_sharing_names_the_missing_dependency(self, owner):
        """
        Team membership genuinely lives in Supabase, so there is no correct
        local answer — but the response should say that rather than return a
        bare 503.
        """
        rid = _report_for(owner)
        res = client.post(
            f"/api/v1/reports/{rid}/share", headers=owner["headers"], json={"team_id": "t1"}
        )
        assert res.status_code == 503
        assert res.json()["error"] == "database_required"
        message = res.json()["message"].lower()
        assert "team" in message
        assert "comments and votes still work" in message


class TestCopilotAccessControl:
    def test_owner_can_save_and_read_back(self, owner):
        rid = _report_for(owner)
        res = client.post(
            f"/api/v1/reports/{rid}/copilot",
            headers=owner["headers"],
            json={
                "scorecard": [{"category": "technical_depth", "score": 4, "notes": "solid"}],
                "custom_questions": [],
                "interview_notes": "Probe the EKS migration.",
            },
        )
        assert res.status_code == 200
        body = client.get(f"/api/v1/reports/{rid}/copilot", headers=owner["headers"]).json()
        assert body["copilot"]["interview_notes"] == "Probe the EKS migration."

    def test_a_partially_rated_scorecard_saves(self, owner):
        """
        Score 0 means "not yet rated". The schema required >=1, so a save
        part-way through an interview returned 422 and took the notes with
        it — the normal case, failing.
        """
        rid = _report_for(owner)
        res = client.post(
            f"/api/v1/reports/{rid}/copilot",
            headers=owner["headers"],
            json={
                "scorecard": [
                    {"category": "technical_depth", "score": 0, "notes": ""},
                    {"category": "problem_solving", "score": 3, "notes": "ok"},
                ],
                "custom_questions": [],
                "interview_notes": "Half way through.",
            },
        )
        assert res.status_code == 200, res.text

    def test_a_stranger_cannot_read_private_interview_notes(self, owner, stranger):
        rid = _report_for(owner)
        client.post(
            f"/api/v1/reports/{rid}/copilot",
            headers=owner["headers"],
            json={
                "scorecard": [],
                "custom_questions": [],
                "interview_notes": "CONFIDENTIAL: asking 40L, we can go to 35L",
            },
        )
        res = client.get(f"/api/v1/reports/{rid}/copilot", headers=stranger["headers"])
        assert res.status_code == 404
        assert "CONFIDENTIAL" not in res.text
        assert "40L" not in res.text

    def test_a_stranger_cannot_overwrite_interview_notes(self, owner, stranger):
        rid = _report_for(owner)
        client.post(
            f"/api/v1/reports/{rid}/copilot",
            headers=owner["headers"],
            json={"scorecard": [], "custom_questions": [], "interview_notes": "Mine"},
        )
        res = client.post(
            f"/api/v1/reports/{rid}/copilot",
            headers=stranger["headers"],
            json={"scorecard": [], "custom_questions": [], "interview_notes": "OVERWRITTEN"},
        )
        assert res.status_code == 404

        still = client.get(f"/api/v1/reports/{rid}/copilot", headers=owner["headers"]).json()
        assert still["copilot"]["interview_notes"] == "Mine"

    def test_copilot_data_survives_a_restart(self, owner):
        rid = _report_for(owner)
        client.post(
            f"/api/v1/reports/{rid}/copilot",
            headers=owner["headers"],
            json={"scorecard": [], "custom_questions": [], "interview_notes": "Durable"},
        )
        _jobs.clear()
        body = client.get(f"/api/v1/reports/{rid}/copilot", headers=owner["headers"]).json()
        assert body["copilot"]["interview_notes"] == "Durable"

    def test_copilot_on_a_nonexistent_report_is_not_found(self, owner):
        res = client.get(f"/api/v1/reports/{uuid.uuid4()}/copilot", headers=owner["headers"])
        assert res.status_code == 404

    def test_oversized_notes_are_rejected(self, owner):
        rid = _report_for(owner)
        res = client.post(
            f"/api/v1/reports/{rid}/copilot",
            headers=owner["headers"],
            json={"scorecard": [], "custom_questions": [], "interview_notes": "x" * 6000},
        )
        assert res.status_code == 422
