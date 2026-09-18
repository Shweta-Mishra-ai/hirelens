"""
A finished analysis must not be lost with the process that ran it.

Analysis progress lives in `_jobs`, a process-local dict. The report does
not — it is written to storage the moment analysis finishes. A restart
between those two facts left a recruiter polling for a job this process had
never heard of, while their finished report sat on the dashboard. The
endpoint answered 404, the UI said "Analysis job not found. Please try
uploading again", and they paid for a second analysis of the same CV.

On a free tier the container is replaced on every deploy and every wake
from sleep, and an analysis takes up to two minutes — so this is the normal
case, not an edge case.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.analysis import _jobs
from app.core import local_db
from app.core.dependencies import get_db
from app.main import app
from tests.fake_supabase import FakeSupabase

client = TestClient(app)


def signup(email, name="Rec Ruiter"):
    creds = {"email": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": name})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    payload = res.json()
    return {
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user_id": payload["user"]["id"],
    }


@pytest.fixture
def recruiter():
    return signup("recovery@example.com")


@pytest.fixture
def stranger():
    return signup("recovery_stranger@example.com", "Stran Ger")


def report_blob(name="Anita Rao"):
    return {
        "candidate": {"name": name},
        "credibility": {"overall": 82, "recommendation": "recommended"},
        "file_name": "anita.pdf",
    }


class TestLocalStore:
    def test_a_lost_job_is_recovered_from_the_local_store(self, recruiter, fresh_local_db):
        job_id, report_id = str(uuid.uuid4()), str(uuid.uuid4())
        fresh_local_db.save_report(
            report_id=report_id, user_id=recruiter["user_id"], file_name="anita.pdf",
            candidate_name="Anita Rao", overall_score=82, recommendation="recommended",
            report_data=report_blob(), job_id=job_id,
        )
        assert job_id not in _jobs  # the process has no memory of it

        res = client.get(f"/api/v1/analysis/{job_id}/status", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "complete"
        assert body["progress"] == 100
        assert body["report_id"] == report_id
        assert body["file_name"] == "anita.pdf"
        assert body["error"] is None

    def test_the_recovered_report_actually_opens(self, recruiter, fresh_local_db):
        job_id, report_id = str(uuid.uuid4()), str(uuid.uuid4())
        blob = report_blob()
        blob["_owner_user_id"] = recruiter["user_id"]
        fresh_local_db.save_report(
            report_id=report_id, user_id=recruiter["user_id"], file_name="anita.pdf",
            candidate_name="Anita Rao", overall_score=82, recommendation="recommended",
            report_data=blob, job_id=job_id,
        )
        report_id_from_poll = client.get(
            f"/api/v1/analysis/{job_id}/status", headers=recruiter["headers"]
        ).json()["report_id"]

        opened = client.get(f"/api/v1/reports/{report_id_from_poll}", headers=recruiter["headers"])
        assert opened.status_code == 200, opened.text
        assert opened.json()["candidate"]["name"] == "Anita Rao"

    def test_someone_else_s_job_is_not_recovered_for_you(self, recruiter, stranger, fresh_local_db):
        job_id, report_id = str(uuid.uuid4()), str(uuid.uuid4())
        fresh_local_db.save_report(
            report_id=report_id, user_id=recruiter["user_id"], file_name="anita.pdf",
            candidate_name="Anita Rao", overall_score=82, recommendation="recommended",
            report_data=report_blob(), job_id=job_id,
        )
        res = client.get(f"/api/v1/analysis/{job_id}/status", headers=stranger["headers"])
        assert res.status_code == 404

    def test_a_job_that_never_existed_is_still_a_404(self, recruiter, fresh_local_db):
        res = client.get(f"/api/v1/analysis/{uuid.uuid4()}/status", headers=recruiter["headers"])
        assert res.status_code == 404
        assert "dashboard" in res.json()["message"].lower()

    def test_a_live_job_still_reports_its_own_progress(self, recruiter, fresh_local_db):
        """Recovery must not shadow a job this process is actually running."""
        job_id = str(uuid.uuid4())
        _jobs[job_id] = {
            "id": job_id, "user_id": recruiter["user_id"], "status": "running",
            "stage": "analyzing", "progress": 45, "file_name": "anita.pdf",
            "report_id": None, "error": None,
        }
        body = client.get(f"/api/v1/analysis/{job_id}/status", headers=recruiter["headers"]).json()
        assert body["status"] == "running"
        assert body["progress"] == 45

    def test_a_failed_job_is_not_reported_as_complete(self, recruiter, fresh_local_db):
        job_id = str(uuid.uuid4())
        _jobs[job_id] = {
            "id": job_id, "user_id": recruiter["user_id"], "status": "failed",
            "stage": "failed", "progress": 0, "file_name": "bad.pdf",
            "report_id": None, "error": "Could not read this PDF.",
        }
        body = client.get(f"/api/v1/analysis/{job_id}/status", headers=recruiter["headers"]).json()
        assert body["status"] == "failed"
        assert body["error"] == "Could not read this PDF."


class TestSupabase:
    @pytest.fixture
    def db(self, recruiter):
        fake = FakeSupabase({"reports": []})
        app.dependency_overrides[get_db] = lambda: fake
        yield fake
        app.dependency_overrides.pop(get_db, None)

    def test_a_lost_job_is_recovered_from_supabase(self, recruiter, db):
        job_id, report_id = str(uuid.uuid4()), str(uuid.uuid4())
        db.tables["reports"].append({
            "id": report_id, "user_id": recruiter["user_id"], "job_id": job_id,
            "file_name": "anita.pdf", "candidate_name": "Anita Rao",
            "overall_score": 82, "recommendation": "recommended",
            "report_data": report_blob(),
        })
        body = client.get(f"/api/v1/analysis/{job_id}/status", headers=recruiter["headers"]).json()
        assert body["status"] == "complete"
        assert body["report_id"] == report_id

    def test_another_recruiter_s_report_is_not_handed_over(self, recruiter, stranger, db):
        job_id = str(uuid.uuid4())
        db.tables["reports"].append({
            "id": "r1", "user_id": stranger["user_id"], "job_id": job_id,
            "file_name": "anita.pdf", "report_data": report_blob(),
        })
        res = client.get(f"/api/v1/analysis/{job_id}/status", headers=recruiter["headers"])
        assert res.status_code == 404

    def test_a_database_failure_falls_back_rather_than_erroring(self, recruiter, db, fresh_local_db):
        job_id, report_id = str(uuid.uuid4()), str(uuid.uuid4())
        db.fail("reports", "select")
        fresh_local_db.save_report(
            report_id=report_id, user_id=recruiter["user_id"], file_name="anita.pdf",
            candidate_name="Anita Rao", overall_score=82, recommendation="recommended",
            report_data=report_blob(), job_id=job_id,
        )
        body = client.get(f"/api/v1/analysis/{job_id}/status", headers=recruiter["headers"]).json()
        assert body["report_id"] == report_id


def test_the_job_id_is_stored_alongside_the_report(fresh_local_db):
    """Recovery depends on it, and databases created before this existed
    have no such column — the migration has to add it."""
    job_id, report_id = str(uuid.uuid4()), str(uuid.uuid4())
    fresh_local_db.save_report(
        report_id=report_id, user_id="u1", file_name="a.pdf", candidate_name="A",
        overall_score=50, recommendation="manual_review", report_data={}, job_id=job_id,
    )
    found = fresh_local_db.find_report_by_job(job_id, "u1")
    assert found and found["id"] == report_id
    assert fresh_local_db.find_report_by_job(job_id, "someone-else") is None
    assert fresh_local_db.find_report_by_job("", "u1") is None
