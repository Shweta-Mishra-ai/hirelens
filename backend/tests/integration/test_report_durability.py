"""
Report durability across a process restart.

The gap this covers: without Supabase, analysed reports lived only in
`analysis._jobs`, a process-local dict. Render's free tier sleeps the
container after ~15 minutes idle and restarts it on the next request, and
every redeploy restarts it too. A recruiter could analyse fifty candidates in
the morning and find an empty dashboard after lunch — no error, nothing to
recover, and no indication anything had been lost.

`_jobs.clear()` here stands in for that restart: it is exactly what the
process loses. Anything that survives it came from the durable store.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.analysis import _jobs, _stamp_report_metadata, _persist_report_locally
from app.core import local_db
from app.main import app

client = TestClient(app)


def _report_blob(name="Priya Raghavan", score=74, recommendation="manual_review"):
    return {
        "candidate": {"name": name, "email": "priya@example.com"},
        "credibility": {"overall": score, "recommendation": recommendation, "sub_scores": {}},
        "skills": {"all_claimed": ["Python", "Kafka"], "verified_by_evidence": ["Python"]},
        "flags": [{"severity": "medium", "category": "skills", "title": "A flag",
                   "description": "d", "evidence": "e", "action": "a"}],
        "summary": "A summary.",
    }


@pytest.fixture
def user():
    email = f"durable_{uuid.uuid4().hex[:8]}@example.com"
    res = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "Durable Tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _store(user, report_id, **kw):
    """Analyse-and-store, minus the AI call."""
    blob = _report_blob(**kw)
    _stamp_report_metadata(blob, user_id=user["id"], filename="cv.pdf", report_id=report_id)
    _persist_report_locally(blob, report_id=report_id, user_id=user["id"], filename="cv.pdf")
    _jobs[f"report_{report_id}"] = blob
    return blob


def _restart():
    """Simulate the process restarting: everything in memory is gone."""
    _jobs.clear()


class TestSurvivesRestart:
    def test_report_is_readable_after_a_restart(self, user):
        rid = str(uuid.uuid4())
        _store(user, rid)

        _restart()

        res = client.get(f"/api/v1/reports/{rid}", headers=user["headers"])
        assert res.status_code == 200, "report did not survive the restart"
        assert res.json()["candidate"]["name"] == "Priya Raghavan"

    def test_report_still_appears_in_the_list_after_a_restart(self, user):
        rid = str(uuid.uuid4())
        _store(user, rid)

        _restart()

        body = client.get("/api/v1/reports", headers=user["headers"]).json()
        assert body["total"] >= 1
        assert any(r["id"] == rid for r in body["reports"])

    def test_list_row_keeps_its_metadata_after_a_restart(self, user):
        rid = str(uuid.uuid4())
        _store(user, rid)
        _restart()

        row = next(
            r for r in client.get("/api/v1/reports", headers=user["headers"]).json()["reports"]
            if r["id"] == rid
        )
        assert row["file_name"] == "cv.pdf"
        assert row["candidate_name"] == "Priya Raghavan"
        assert row["overall_score"] == 74
        assert row["created_at"], "created_at must survive, or the UI shows a dash"

    def test_analytics_counts_persisted_reports_after_a_restart(self, user):
        for _ in range(3):
            _store(user, str(uuid.uuid4()))
        _restart()

        body = client.get("/api/v1/reports/analytics", headers=user["headers"]).json()
        assert body["total_candidates"] >= 3

    def test_decision_survives_a_restart(self, user):
        rid = str(uuid.uuid4())
        _store(user, rid)

        res = client.post(
            f"/api/v1/reports/{rid}/decision",
            headers=user["headers"],
            json={"decision": "advance", "notes": "Strong ledger work"},
        )
        assert res.status_code == 200

        _restart()

        assert client.get(f"/api/v1/reports/{rid}", headers=user["headers"]).json()[
            "recruiter_decision"
        ] == "advance"

    def test_decision_response_makes_no_training_claim(self, user):
        """Recruiter decisions are stored, not used to train anything."""
        rid = str(uuid.uuid4())
        _store(user, rid)
        body = client.post(
            f"/api/v1/reports/{rid}/decision",
            headers=user["headers"],
            json={"decision": "advance"},
        ).json()
        lowered = body["message"].lower()
        assert "train" not in lowered
        assert "improve ai" not in lowered

    def test_deleted_report_does_not_come_back_after_a_restart(self, user):
        rid = str(uuid.uuid4())
        _store(user, rid)
        assert client.delete(f"/api/v1/reports/{rid}", headers=user["headers"]).status_code in (200, 204)

        _restart()

        assert client.get(f"/api/v1/reports/{rid}", headers=user["headers"]).status_code == 404


class TestOwnership:
    def test_a_persisted_report_is_not_readable_by_another_user(self, user):
        rid = str(uuid.uuid4())
        _store(user, rid)
        _restart()

        other = client.post(
            "/api/v1/auth/signup",
            json={
                "email": f"other_{uuid.uuid4().hex[:8]}@example.com",
                "password": "Password123!",
                "full_name": "Other Recruiter",
            },
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}

        assert client.get(f"/api/v1/reports/{rid}", headers=other_headers).status_code in (403, 404)
        assert not any(
            r["id"] == rid
            for r in client.get("/api/v1/reports", headers=other_headers).json()["reports"]
        )

    def test_another_user_cannot_record_a_decision(self, user):
        rid = str(uuid.uuid4())
        _store(user, rid)
        _restart()

        other = client.post(
            "/api/v1/auth/signup",
            json={
                "email": f"nosy_{uuid.uuid4().hex[:8]}@example.com",
                "password": "Password123!",
                "full_name": "Nosy Recruiter",
            },
        ).json()
        res = client.post(
            f"/api/v1/reports/{rid}/decision",
            headers={"Authorization": f"Bearer {other['access_token']}"},
            json={"decision": "reject"},
        )
        assert res.status_code in (403, 404)


class TestStorageFailures:
    def test_a_storage_failure_does_not_fail_the_analysis(self, user, monkeypatch):
        """
        A completed analysis must still be returned to the user even if it
        cannot be written to disk — the in-memory copy is still good for
        this process.
        """
        monkeypatch.setattr(local_db, "save_report", lambda **kw: False)
        rid = str(uuid.uuid4())
        _store(user, rid)  # must not raise
        assert client.get(f"/api/v1/reports/{rid}", headers=user["headers"]).status_code == 200

    def test_unreadable_stored_json_is_treated_as_missing(self, user):
        rid = str(uuid.uuid4())
        _store(user, rid)
        with local_db._get_connection() as conn:
            conn.execute("UPDATE reports SET report_data = ? WHERE id = ?", ("{not json", rid))
            conn.commit()

        _restart()

        # Corrupt data must not 500 — it reads as absent.
        assert client.get(f"/api/v1/reports/{rid}", headers=user["headers"]).status_code == 404
