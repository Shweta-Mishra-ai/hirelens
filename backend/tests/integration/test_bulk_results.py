"""
What a recruiter does with a batch once it has run.

tests/unit/test_bulk.py covers the upload guards. Everything after that —
the ranking, the CSV, the duplicate check and the notify-all blast — was
untested, even though notify-all can send real email to every candidate in
a batch and the ranking is the entire point of bulk upload.

Batches are seeded directly into the job and batch stores here, so no
analysis (and no LLM call) is involved.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import bulk as bulk_ep
from app.api.v1.endpoints.analysis import _jobs
from app.core.dependencies import get_db
from app.main import app
from app.services.queue import batch_store
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
    }


@pytest.fixture
def owner():
    return signup("bulk_owner@example.com", "Bulk Owner")


@pytest.fixture
def stranger():
    return signup("bulk_stranger@example.com", "Bulk Stranger")


def report(name, score, rec="recommended", email=None, bullets=("Built a payments service",)):
    return {
        "candidate": {"name": name, "email": email},
        "credibility": {"overall": score, "recommendation": rec},
        "experience": [{"company": "Acme", "responsibilities": list(bullets)}],
        "file_name": f"{name.lower().replace(' ', '_')}.pdf",
    }


@pytest.fixture
def batch(owner):
    """Three finished analyses and one still running."""
    people = [
        ("j1", "Anita Rao", 91, "recommended", "anita@example.com"),
        ("j2", "Bharat Shah", 62, "manual_review", "bharat@example.com"),
        ("j3", "Chetan Iyer", 77, "recommended", None),
    ]
    job_ids = []
    for jid, name, score, rec, email in people:
        rid = f"rep_{jid}"
        _jobs[jid] = {
            "id": jid, "user_id": owner["user_id"], "batch_id": "b1",
            "status": "complete", "stage": "complete", "progress": 100,
            "file_name": f"{jid}.pdf", "report_id": rid, "error": None,
        }
        data = report(name, score, rec, email)
        data["_owner_user_id"] = owner["user_id"]
        _jobs[f"report_{rid}"] = data
        job_ids.append(jid)

    _jobs["j4"] = {
        "id": "j4", "user_id": owner["user_id"], "batch_id": "b1",
        "status": "running", "stage": "analyzing", "progress": 45,
        "file_name": "j4.pdf", "report_id": None, "error": None,
    }
    job_ids.append("j4")

    batch_store.create_batch(None, "b1", owner["user_id"], job_ids, total=len(job_ids))
    yield {"id": "b1", "job_ids": job_ids}


class TestStatus:
    def test_status_reports_progress_and_a_live_ranking(self, owner, batch):
        res = client.get("/api/v1/bulk/b1/status", headers=owner["headers"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 4
        assert body["complete"] == 3
        assert body["running"] == 1
        assert body["is_done"] is False
        assert [r["candidate_name"] for r in body["ranking"]] == ["Anita Rao", "Chetan Iyer", "Bharat Shah"]
        assert [r["rank"] for r in body["ranking"]] == [1, 2, 3]

    def test_a_batch_is_done_only_when_every_job_is(self, owner, batch):
        _jobs["j4"] = {**_jobs["j4"], "status": "failed", "stage": "failed", "error": "unreadable pdf"}
        body = client.get("/api/v1/bulk/b1/status", headers=owner["headers"]).json()
        assert body["failed"] == 1
        assert body["is_done"] is True

    def test_a_job_that_expired_is_reported_rather_than_dropped(self, owner, batch):
        """Losing a job silently would make the counts stop adding up."""
        _jobs.pop("j4")
        body = client.get("/api/v1/bulk/b1/status", headers=owner["headers"]).json()
        assert body["total"] == 4
        assert len(body["jobs"]) == 4
        missing = next(j for j in body["jobs"] if j["id"] == "j4")
        assert missing["status"] == "failed"
        assert "expired" in missing["error"].lower()

    def test_an_unknown_batch_is_a_404(self, owner):
        assert client.get("/api/v1/bulk/nope/status", headers=owner["headers"]).status_code == 404

    def test_someone_else_s_batch_is_refused(self, stranger, batch):
        assert client.get("/api/v1/bulk/b1/status", headers=stranger["headers"]).status_code == 403

    def test_status_requires_authentication(self, batch):
        assert client.get("/api/v1/bulk/b1/status").status_code in (401, 403)


class TestCsvExport:
    def test_the_csv_is_the_ranking_in_order(self, owner, batch):
        res = client.get("/api/v1/bulk/b1/export.csv", headers=owner["headers"])
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")
        rows = [r.split(",") for r in res.text.strip().splitlines()]
        assert rows[0][0] == "Rank"
        assert [r[1] for r in rows[1:]] == ["Anita Rao", "Chetan Iyer", "Bharat Shah"]
        assert rows[1][3] == "91"

    def test_the_filename_names_the_batch(self, owner, batch):
        res = client.get("/api/v1/bulk/b1/export.csv", headers=owner["headers"])
        assert "hirelens_ranking_b1" in res.headers["content-disposition"]

    def test_someone_else_s_batch_cannot_be_exported(self, stranger, batch):
        assert client.get("/api/v1/bulk/b1/export.csv", headers=stranger["headers"]).status_code == 403


class TestDuplicateCheck:
    def test_candidates_with_near_identical_resumes_are_clustered(self, owner):
        shared = (
            "Led the migration of a monolithic payments platform to event-driven microservices",
            "Reduced p99 checkout latency from 1400ms to 220ms across three regions",
            "Mentored four engineers and ran the on-call rotation for the payments group",
        )
        job_ids = []
        for i, name in enumerate(["Twin One", "Twin Two", "Original Person"]):
            jid = f"d{i}"
            rid = f"rep_{jid}"
            _jobs[jid] = {
                "id": jid, "user_id": owner["user_id"], "batch_id": "bd",
                "status": "complete", "stage": "complete", "progress": 100,
                "file_name": f"{jid}.pdf", "report_id": rid, "error": None,
            }
            bullets = shared if i < 2 else ("Taught secondary school physics for six years",)
            data = report(name, 70, bullets=bullets)
            data["_owner_user_id"] = owner["user_id"]
            _jobs[f"report_{rid}"] = data
            job_ids.append(jid)
        batch_store.create_batch(None, "bd", owner["user_id"], job_ids, total=3)

        body = client.get("/api/v1/bulk/bd/duplicates", headers=owner["headers"]).json()
        assert body["candidates_compared"] == 3
        assert len(body["clusters"]) == 1
        assert "Twin One" in str(body["clusters"])
        assert "Original Person" not in str(body["clusters"])

    def test_distinct_resumes_produce_no_clusters(self, owner, batch):
        body = client.get("/api/v1/bulk/b1/duplicates", headers=owner["headers"]).json()
        assert body["clusters"] == []

    def test_someone_else_s_batch_cannot_be_checked(self, stranger, batch):
        assert client.get("/api/v1/bulk/b1/duplicates", headers=stranger["headers"]).status_code == 403


class TestNotifyAll:
    @pytest.fixture
    def mailer(self, monkeypatch):
        sent = []

        async def fake_send(to_email, subject, body):
            sent.append({"to": to_email, "subject": subject, "body": body})
            return True

        import app.services.email.sender as sender
        monkeypatch.setattr(sender, "send_candidate_decision_email", fake_send)
        return sent

    def test_everyone_with_an_email_on_file_is_notified(self, owner, batch, mailer):
        res = client.post(
            "/api/v1/bulk/b1/notify-all", headers=owner["headers"], json={"decision": "reject"}
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total_candidates"] == 3
        assert body["emails_sent"] == 2
        assert {m["to"] for m in mailer} == {"anita@example.com", "bharat@example.com"}

    def test_a_candidate_without_an_email_is_reported_not_silently_skipped(self, owner, batch, mailer):
        body = client.post(
            "/api/v1/bulk/b1/notify-all", headers=owner["headers"], json={"decision": "advance"}
        ).json()
        chetan = next(r for r in body["results"] if r["candidate_name"] == "Chetan Iyer")
        assert chetan["email_sent"] is False
        assert chetan["reason"] == "no_email_on_file"

    def test_a_per_candidate_override_replaces_the_template(self, owner, batch, mailer):
        client.post(
            "/api/v1/bulk/b1/notify-all",
            headers=owner["headers"],
            json={
                "decision": "advance",
                "overrides": {
                    "rep_j1": {"subject": "Final round at Acme", "body": "Hi Anita, are you free Thursday?"}
                },
            },
        )
        anita = next(m for m in mailer if m["to"] == "anita@example.com")
        bharat = next(m for m in mailer if m["to"] == "bharat@example.com")
        assert anita["subject"] == "Final round at Acme"
        assert bharat["subject"] != "Final round at Acme"

    def test_the_email_is_signed_with_the_recruiter_s_name(self, owner, batch, mailer):
        """The JWT carries only an id and an email, so this used to sign
        every candidate email with the recruiter's raw email address. The
        name has been in the users table the whole time."""
        client.post("/api/v1/bulk/b1/notify-all", headers=owner["headers"], json={"decision": "advance"})
        body = mailer[0]["body"]
        assert "Bulk Owner" in body
        assert "bulk_owner@example.com" not in body

    def test_notifying_does_not_record_a_hiring_decision(self, owner, batch, mailer):
        """Sending an email and recording a decision stay independent."""
        client.post("/api/v1/bulk/b1/notify-all", headers=owner["headers"], json={"decision": "reject"})
        assert _jobs["report_rep_j1"].get("recruiter_decision") is None

    def test_an_unknown_decision_is_rejected_before_any_email_goes_out(self, owner, batch, mailer):
        res = client.post(
            "/api/v1/bulk/b1/notify-all", headers=owner["headers"], json={"decision": "ghost them"}
        )
        assert res.status_code == 422
        assert mailer == []

    def test_someone_else_s_batch_cannot_be_blasted(self, stranger, batch, mailer):
        res = client.post(
            "/api/v1/bulk/b1/notify-all", headers=stranger["headers"], json={"decision": "reject"}
        )
        assert res.status_code == 403
        assert mailer == []

    def test_an_unknown_batch_sends_nothing(self, owner, mailer):
        res = client.post(
            "/api/v1/bulk/nope/notify-all", headers=owner["headers"], json={"decision": "reject"}
        )
        assert res.status_code == 404
        assert mailer == []

    def test_a_provider_failure_is_reported_per_candidate(self, owner, batch, monkeypatch):
        async def fails(to_email, subject, body):
            return False

        import app.services.email.sender as sender
        monkeypatch.setattr(sender, "send_candidate_decision_email", fails)
        body = client.post(
            "/api/v1/bulk/b1/notify-all", headers=owner["headers"], json={"decision": "reject"}
        ).json()
        assert body["emails_sent"] == 0
        assert {r["reason"] for r in body["results"]} == {"provider_unavailable", "no_email_on_file"}


class TestRankingFromTheDatabase:
    def test_the_ranking_prefers_the_stored_row_over_the_process_cache(self, owner, batch):
        """After a restart the cache is gone; the ranking has to come from
        the database rather than silently losing candidates."""
        fake = FakeSupabase({
            "reports": [
                {"id": "rep_j1", "file_name": "anita.pdf", "candidate_name": "Anita Rao",
                 "overall_score": 95, "recommendation": "recommended"},
                {"id": "rep_j2", "file_name": "bharat.pdf", "candidate_name": "Bharat Shah",
                 "overall_score": 40, "recommendation": "high_risk"},
                {"id": "rep_j3", "file_name": "chetan.pdf", "candidate_name": "Chetan Iyer",
                 "overall_score": 77, "recommendation": "recommended"},
            ],
        })
        app.dependency_overrides[get_db] = lambda: fake
        try:
            body = client.get("/api/v1/bulk/b1/status", headers=owner["headers"]).json()
            assert [r["overall_score"] for r in body["ranking"]] == [95, 77, 40]
            assert body["ranking"][2]["recommendation"] == "high_risk"
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_a_database_lookup_failure_falls_back_to_the_cache(self, owner, batch):
        fake = FakeSupabase({"reports": []})
        fake.fail("reports", "select")
        app.dependency_overrides[get_db] = lambda: fake
        try:
            body = client.get("/api/v1/bulk/b1/status", headers=owner["headers"]).json()
            assert len(body["ranking"]) == 3
            assert body["ranking"][0]["candidate_name"] == "Anita Rao"
        finally:
            app.dependency_overrides.pop(get_db, None)
