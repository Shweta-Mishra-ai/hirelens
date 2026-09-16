"""
Interview notes on the Supabase path.

The co-pilot holds the most sensitive text in the product — compensation
expectations, candid assessments — and it had already leaked across tenants
once, when the read path took a report id with no access check at all. Every
test for that fix ran against the local store; this file runs the Supabase
one, which is what a deployed instance uses.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db
from app.main import app
from app.services.teams import access
from tests.fake_supabase import FakeSupabase

client = TestClient(app)

PRIVATE = "PRIVATE: asked for 40L, we can go to 35L max."


def signup(email, name):
    creds = {"email": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": name})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    payload = res.json()
    return {
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user_id": payload["user_id"] if "user_id" in payload else payload["user"]["id"],
    }


@pytest.fixture
def owner():
    return signup("cp_owner@example.com", "Owner Olsen")


@pytest.fixture
def teammate():
    return signup("cp_mate@example.com", "Mate Mehra")


@pytest.fixture
def outsider():
    return signup("cp_outsider@example.com", "Out Sider")


@pytest.fixture
def db(owner, teammate):
    fake = FakeSupabase({
        "reports": [
            {"id": "rep1", "user_id": owner["user_id"], "team_id": None,
             "candidate_name": "Anita Rao", "file_name": "anita.pdf",
             "report_data": {"candidate": {"name": "Anita Rao"}}},
        ],
        "team_members": [
            {"team_id": "t1", "user_id": owner["user_id"], "role": "owner"},
            {"team_id": "t1", "user_id": teammate["user_id"], "role": "member"},
        ],
    })
    app.dependency_overrides[get_db] = lambda: fake
    access._mem_teams.clear()
    access._mem_team_members.clear()
    access._mem_team_invites.clear()
    yield fake
    app.dependency_overrides.pop(get_db, None)


def save(headers, notes=PRIVATE, **extra):
    body = {
        "scorecard": [{"category": "Systems design", "score": 4, "notes": "Solid"}],
        "custom_questions": [{"question": "Walk me through the ledger work", "is_asked": False}],
        "interview_notes": notes,
        "recommendation_override": None,
    }
    body.update(extra)
    return client.post("/api/v1/reports/rep1/copilot", headers=headers, json=body)


class TestOwnerAccess:
    def test_notes_save_into_the_report_row(self, owner, db):
        res = save(owner["headers"])
        assert res.status_code == 200, res.text
        stored = db.tables["reports"][0]["report_data"]["copilot_data"]
        assert stored["interview_notes"] == PRIVATE
        assert stored["scorecard"][0]["category"] == "Systems design"

    def test_the_owner_reads_their_own_notes_back(self, owner, db):
        save(owner["headers"])
        res = client.get("/api/v1/reports/rep1/copilot", headers=owner["headers"])
        assert res.status_code == 200, res.text
        assert res.json()["copilot"]["interview_notes"] == PRIVATE

    def test_saving_does_not_discard_the_rest_of_the_report(self, owner, db):
        save(owner["headers"])
        data = db.tables["reports"][0]["report_data"]
        assert data["candidate"]["name"] == "Anita Rao"

    def test_a_report_with_no_notes_yet_returns_an_empty_object(self, owner, db):
        res = client.get("/api/v1/reports/rep1/copilot", headers=owner["headers"])
        assert res.status_code == 200
        assert res.json()["copilot"] == {}

    def test_an_unrated_category_is_accepted(self, owner, db):
        res = save(owner["headers"], scorecard=[{"category": "Systems design", "notes": ""}])
        assert res.status_code == 200, res.text

    def test_a_score_outside_the_scale_is_rejected(self, owner, db):
        res = save(owner["headers"], scorecard=[{"category": "x", "score": 9}])
        assert res.status_code == 422


class TestOtherPeople:
    def test_an_outsider_cannot_read_the_notes(self, owner, outsider, db):
        save(owner["headers"])
        res = client.get("/api/v1/reports/rep1/copilot", headers=outsider["headers"])
        assert res.status_code == 404
        assert PRIVATE not in res.text

    def test_an_outsider_cannot_overwrite_the_notes(self, owner, outsider, db):
        save(owner["headers"])
        res = save(outsider["headers"], notes="wiped")
        assert res.status_code == 404
        assert db.tables["reports"][0]["report_data"]["copilot_data"]["interview_notes"] == PRIVATE

    def test_a_teammate_cannot_read_notes_on_an_unshared_report(self, owner, teammate, db):
        save(owner["headers"])
        res = client.get("/api/v1/reports/rep1/copilot", headers=teammate["headers"])
        assert res.status_code == 404

    def test_a_teammate_can_read_notes_once_the_report_is_shared(self, owner, teammate, db):
        save(owner["headers"])
        db.tables["reports"][0]["team_id"] = "t1"
        res = client.get("/api/v1/reports/rep1/copilot", headers=teammate["headers"])
        assert res.status_code == 200, res.text
        assert res.json()["copilot"]["interview_notes"] == PRIVATE

    def test_an_unknown_report_is_not_found(self, owner, db):
        assert client.get("/api/v1/reports/nope/copilot", headers=owner["headers"]).status_code == 404

    def test_reading_requires_authentication(self, db):
        assert client.get("/api/v1/reports/rep1/copilot").status_code in (401, 403)


class TestDegradation:
    def test_an_unreachable_database_does_not_claim_the_candidate_is_gone(self, owner, db):
        """A 404 here would tell a recruiter their candidate does not exist
        when the database merely did not answer — and that is a thing they
        act on. Same rule the reports list already follows."""
        save(owner["headers"])
        db.fail("reports", "select")
        res = client.get("/api/v1/reports/rep1/copilot", headers=owner["headers"])
        assert res.status_code == 503, res.text
        assert res.json()["error"] == "copilot_unavailable"
        assert "nothing has been lost" in res.json()["message"].lower()

    def test_a_failed_write_is_reported_rather_than_claimed_as_saved(self, owner, db):
        """There is no honest backstop for a report that lives only in
        Supabase, so the one correct answer is to say the save failed —
        never to return 200 over notes that went nowhere."""
        db.fail("reports", "update")
        res = save(owner["headers"])
        assert res.status_code >= 400
        assert "could not save" in res.json()["message"].lower()

    def test_a_malformed_report_blob_does_not_error(self, owner, db):
        db.tables["reports"][0]["report_data"] = "not a dict"
        res = client.get("/api/v1/reports/rep1/copilot", headers=owner["headers"])
        assert res.status_code == 200, res.text
        assert save(owner["headers"]).status_code == 200
