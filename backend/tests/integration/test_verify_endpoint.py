"""
The verification run, end to end.

/verify/{id}/run is the endpoint that decides whether a candidate's claims
hold up against public data, and — since the recommendation-downgrade rule
was added — it is also the only thing that can overrule the AI's headline
verdict. It had no integration test: not for ownership, not for the rule
that one failing check must not take the other three down with it, and not
for the downgrade itself.

The four checks are stubbed here. What they do on a real network is
covered in tests/unit/test_verify_services.py and
tests/unit/test_github_skill_matching.py; what this file pins down is what
the endpoint does with their answers.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import verify as verify_ep
from app.api.v1.endpoints.analysis import _jobs
from app.core.dependencies import get_db
from app.main import app
from tests.fake_supabase import FakeSupabase

client = TestClient(app)


@pytest.fixture
def auth():
    creds = {"email": "verify_run@example.com", "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "Verifier"})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    payload = res.json()
    return {
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user_id": payload["user"]["id"],
    }


def base_report(recommendation="recommended", score=82):
    return {
        "candidate": {"name": "Anita Rao", "github": "https://github.com/anitarao"},
        "skills": {"all_claimed": ["python", "django"]},
        "education": [{"institution": "IIT Bombay"}],
        "certifications": ["AWS Certified"],
        "experience": [{"company": "Acme Labs"}],
        "credibility": {"overall": score, "recommendation": recommendation},
        "ai_content_analysis": {"likelihood": "low"},
    }


@pytest.fixture
def in_memory_report(auth):
    report = base_report()
    report["_owner_user_id"] = auth["user_id"]
    _jobs["report_mem1"] = report
    yield report
    _jobs.pop("report_mem1", None)


@pytest.fixture
def checks(monkeypatch):
    """Stub the four verification services; each test sets what they return."""
    state = {
        "github": {"status": "verified", "username": "anitarao", "verified_skills": ["python"]},
        "education": [{"institution": "IIT Bombay", "status": "verified"}],
        "certifications": [{"name": "AWS Certified", "status": "no_link_provided"}],
        "experience": [{"company": "Acme Labs", "status": "domain_found"}],
    }

    async def gh(username, skills):
        value = state["github"]
        if isinstance(value, Exception):
            raise value
        return value

    async def edu(items):
        value = state["education"]
        if isinstance(value, Exception):
            raise value
        return value

    async def cert(items, name):
        value = state["certifications"]
        if isinstance(value, Exception):
            raise value
        return value

    async def exp(items):
        value = state["experience"]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(verify_ep, "verify_github", gh)
    monkeypatch.setattr(verify_ep, "verify_education", edu)
    monkeypatch.setattr(verify_ep, "verify_certifications", cert)
    monkeypatch.setattr(verify_ep, "verify_experience_companies", exp)
    return state


class TestAccess:
    def test_verification_requires_authentication(self):
        assert client.post("/api/v1/verify/mem1/run").status_code in (401, 403)

    def test_an_unknown_report_is_a_404(self, auth, checks):
        res = client.post("/api/v1/verify/nope/run", headers=auth["headers"])
        assert res.status_code == 404

    def test_someone_else_s_in_memory_report_is_refused(self, auth, checks):
        report = base_report()
        report["_owner_user_id"] = "a-different-recruiter"
        _jobs["report_theirs"] = report
        try:
            res = client.post("/api/v1/verify/theirs/run", headers=auth["headers"])
            assert res.status_code == 403
        finally:
            _jobs.pop("report_theirs", None)

    def test_an_unowned_report_fails_closed(self, auth, checks):
        """A report with no owner stamp must be readable by nobody, not
        everybody."""
        _jobs["report_orphan"] = base_report()
        try:
            res = client.post("/api/v1/verify/orphan/run", headers=auth["headers"])
            assert res.status_code == 403
        finally:
            _jobs.pop("report_orphan", None)


class TestRun:
    def test_a_run_returns_all_four_checks_and_a_trust_assessment(self, auth, checks, in_memory_report):
        res = client.post("/api/v1/verify/mem1/run", headers=auth["headers"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert set(["github", "education", "certifications", "experience", "trust_assessment"]) <= set(body)
        assert body["github"]["status"] == "verified"
        assert body["trust_assessment"]["verdict"] == "high_confidence"
        assert body["run_at"]

    def test_the_result_is_stored_on_the_report(self, auth, checks, in_memory_report):
        client.post("/api/v1/verify/mem1/run", headers=auth["headers"])
        stored = _jobs["report_mem1"]
        assert stored["verification"]["github"]["status"] == "verified"

    def test_a_rerun_overwrites_rather_than_appends(self, auth, checks, in_memory_report):
        client.post("/api/v1/verify/mem1/run", headers=auth["headers"])
        checks["github"] = {"status": "not_found", "username": "anitarao"}
        res = client.post("/api/v1/verify/mem1/run", headers=auth["headers"])
        assert res.json()["github"]["status"] == "not_found"
        assert _jobs["report_mem1"]["verification"]["github"]["status"] == "not_found"

    def test_one_failing_check_does_not_take_the_others_down(self, auth, checks, in_memory_report):
        checks["certifications"] = RuntimeError("cert provider exploded")
        res = client.post("/api/v1/verify/mem1/run", headers=auth["headers"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["certifications"] == []
        assert body["github"]["status"] == "verified"
        assert body["education"][0]["status"] == "verified"

    def test_a_failing_github_check_is_reported_not_faked(self, auth, checks, in_memory_report):
        checks["github"] = RuntimeError("github unreachable")
        body = client.post("/api/v1/verify/mem1/run", headers=auth["headers"]).json()
        assert body["github"]["status"] == "error"
        assert "failed" in body["github"]["note"].lower()

    def test_every_check_failing_still_returns_a_usable_response(self, auth, checks, in_memory_report):
        for key in checks:
            checks[key] = RuntimeError("everything is down")
        res = client.post("/api/v1/verify/mem1/run", headers=auth["headers"])
        assert res.status_code == 200, res.text
        assert res.json()["trust_assessment"]["verdict"] == "insufficient_evidence"

    def test_a_recruiter_supplied_username_overrides_the_resume(
        self, auth, checks, in_memory_report, monkeypatch
    ):
        seen = {}

        async def gh(username, skills):
            seen["username"] = username
            return {"status": "verified", "verified_skills": []}

        monkeypatch.setattr(verify_ep, "verify_github", gh)
        client.post(
            "/api/v1/verify/mem1/run",
            headers=auth["headers"],
            json={"github_username": "different-handle"},
        )
        assert seen["username"] == "different-handle"


class TestRecommendationDowngrade:
    def test_strong_contradicting_evidence_downgrades_the_verdict(self, auth, checks, in_memory_report):
        """A GitHub account that does not exist is exactly the kind of
        evidence that should outrank the AI's initial read."""
        checks["github"] = {"status": "not_found", "username": "anitarao"}
        checks["education"] = [{"institution": "IIT Bombay", "status": "not_found"}]
        res = client.post("/api/v1/verify/mem1/run", headers=auth["headers"])
        body = res.json()
        assert body["trust_assessment"]["verdict"] == "low_confidence"
        assert body["recommendation_update"]["new_recommendation"] == "manual_review"
        assert body["recommendation_update"]["ai_recommendation"] == "recommended"
        assert _jobs["report_mem1"]["credibility"]["recommendation"] == "manual_review"

    def test_a_clean_verification_never_upgrades_the_verdict(self, auth, checks):
        """Verification passing does not resolve concerns verification never
        checked, so it must not promote anyone."""
        report = base_report(recommendation="manual_review", score=60)
        report["_owner_user_id"] = auth["user_id"]
        _jobs["report_up"] = report
        try:
            body = client.post("/api/v1/verify/up/run", headers=auth["headers"]).json()
            assert body["recommendation_update"] is None
            assert _jobs["report_up"]["credibility"]["recommendation"] == "manual_review"
        finally:
            _jobs.pop("report_up", None)

    def test_a_candidate_already_at_the_bottom_is_not_downgraded_further(self, auth, checks):
        report = base_report(recommendation="high_risk", score=30)
        report["_owner_user_id"] = auth["user_id"]
        _jobs["report_low"] = report
        try:
            checks["github"] = {"status": "not_found"}
            body = client.post("/api/v1/verify/low/run", headers=auth["headers"]).json()
            assert body["trust_assessment"]["verdict"] == "low_confidence"
            assert body["recommendation_update"] is None
            assert _jobs["report_low"]["credibility"]["recommendation"] == "high_risk"
        finally:
            _jobs.pop("report_low", None)

    def test_rerunning_on_the_same_evidence_lands_on_the_same_verdict(
        self, auth, checks, in_memory_report
    ):
        """Verification is documented as safe to re-run and it is a button
        a recruiter can click twice. Clicking it again with nothing new
        learned must not walk the candidate down another level."""
        checks["github"] = {"status": "not_found"}
        checks["education"] = [{"institution": "IIT Bombay", "status": "not_found"}]
        first = client.post("/api/v1/verify/mem1/run", headers=auth["headers"]).json()
        assert first["recommendation_update"]["new_recommendation"] == "manual_review"

        second = client.post("/api/v1/verify/mem1/run", headers=auth["headers"]).json()
        cred = _jobs["report_mem1"]["credibility"]
        assert cred["recommendation"] == "manual_review"
        assert cred["ai_recommendation"] == "recommended"
        assert second["recommendation_update"] is None
        assert second["trust_assessment"]["verdict"] == "low_confidence"

    def test_a_third_run_is_still_stable(self, auth, checks, in_memory_report):
        checks["github"] = {"status": "not_found"}
        checks["education"] = [{"institution": "IIT Bombay", "status": "not_found"}]
        for _ in range(3):
            client.post("/api/v1/verify/mem1/run", headers=auth["headers"])
        assert _jobs["report_mem1"]["credibility"]["recommendation"] == "manual_review"

    def test_no_evidence_at_all_never_downgrades(self, auth, checks, in_memory_report):
        checks["github"] = {"status": "no_username"}
        checks["education"] = []
        checks["certifications"] = []
        checks["experience"] = []
        body = client.post("/api/v1/verify/mem1/run", headers=auth["headers"]).json()
        assert body["trust_assessment"]["evidence_available"] is False
        assert body["recommendation_update"] is None


class TestDatabasePath:
    @pytest.fixture
    def db(self, auth):
        fake = FakeSupabase({
            "reports": [{
                "id": "db1",
                "user_id": auth["user_id"],
                "file_name": "anita.pdf",
                "report_data": base_report(),
                "recommendation": "recommended",
            }],
            "team_members": [],
        })
        app.dependency_overrides[get_db] = lambda: fake
        yield fake
        app.dependency_overrides.pop(get_db, None)

    def test_a_report_in_the_database_is_verified_and_written_back(self, auth, checks, db):
        res = client.post("/api/v1/verify/db1/run", headers=auth["headers"])
        assert res.status_code == 200, res.text
        row = db.tables["reports"][0]
        assert row["report_data"]["verification"]["github"]["status"] == "verified"

    def test_someone_else_s_database_report_is_refused(self, auth, checks, db):
        db.tables["reports"][0]["user_id"] = "another-recruiter"
        res = client.post("/api/v1/verify/db1/run", headers=auth["headers"])
        assert res.status_code == 403

    def test_a_downgrade_updates_the_top_level_column_too(self, auth, checks, db):
        """The dashboard reads the column, not the JSON blob — if only the
        blob changed, the list would still show the old verdict."""
        checks["github"] = {"status": "not_found"}
        checks["education"] = [{"institution": "IIT Bombay", "status": "not_found"}]
        client.post("/api/v1/verify/db1/run", headers=auth["headers"])
        row = db.tables["reports"][0]
        assert row["recommendation"] == "manual_review"

    def test_a_failed_database_write_still_leaves_the_result_readable(self, auth, checks, db):
        db.fail("reports", "update")
        res = client.post("/api/v1/verify/db1/run", headers=auth["headers"])
        assert res.status_code == 200, res.text
        # Mirrored into the process cache, stamped with its owner so the
        # owner can still read it rather than it being orphaned.
        cached = _jobs.get("report_db1")
        assert cached is not None
        assert cached["_owner_user_id"] == auth["user_id"]
        _jobs.pop("report_db1", None)

    def test_a_database_read_failure_falls_through_to_the_cache(self, auth, checks, db):
        db.fail("reports", "select")
        report = base_report()
        report["_owner_user_id"] = auth["user_id"]
        _jobs["report_db1"] = report
        try:
            res = client.post("/api/v1/verify/db1/run", headers=auth["headers"])
            assert res.status_code == 200, res.text
        finally:
            _jobs.pop("report_db1", None)
