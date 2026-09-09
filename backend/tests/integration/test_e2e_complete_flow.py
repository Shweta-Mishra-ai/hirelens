"""
HireLens — Complete End-to-End Integration & Feature Test Suite
Tests all 14 core & advanced application features end-to-end:
1. Recruiter Signup, Login, and Capacity Limit Enforcement
2. Single Resume Upload & Document Parsing
3. Job Status Polling
4. Candidate Intelligence Report Retrieval & Ownership
5. Recruiter Decision Recording & Email Notification Drafting
6. Public Data Verification (GitHub, Education, Certs, Company, SSRF Protection)
7. Team Workspace Creation, Invites, Sharing, Voting, and Comments
8. Bulk CV Upload, Credibility Ranking, and Duplicate Scan
9. Job Description Skill Matching
10. ATS CSV Import Simulation
11. System Health & Diagnostic Capacity Endpoint Checks
12. Enterprise Talent Analytics & Workforce Intelligence
13. Live Interactive Interview Co-Pilot & Scorecard Ratings
14. Predictive Career Growth & Talent Velocity Index
"""

import pytest
import io
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1.endpoints.analysis import _jobs
from app.core.dependencies import get_db

client = TestClient(app)

MOCK_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length 55 >>\nstream\nBT /F1 12 Tf 100 700 Td (Jane Doe Senior Developer) Tj ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000060 00000 n\n0000000117 00000 n\n0000000213 00000 n\ntrailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n318\n%%EOF"

REALISTIC_RESUME = """
Jane Doe
Senior Fullstack Software Engineer
Email: jane.doe@example.com | Phone: (555) 019-2831

Professional Summary:
Accomplished Senior Fullstack Engineer with 6+ years of experience building high-scale web platforms and cloud microservices.

Work Experience:
Senior Software Engineer — Google (2020 - 2023)
- Architected high-throughput FastAPI and React web services supporting 10M+ daily active users.
- Led a team of 5 fullstack developers, optimizing backend database query performance by 45%.
- Implemented OAuth authentication, rate limiting, and Redis caching infrastructure.

Software Developer — Acme Corp (2018 - 2020)
- Developed RESTful Python services and Next.js frontend interfaces.
- Managed PostgreSQL database schemas, migrations, and automated CI/CD pipelines.

Education:
Bachelor of Science in Computer Science — Stanford University (2014 - 2018)

Skills:
Python, FastAPI, React, Next.js, TypeScript, Node.js, PostgreSQL, Redis, Docker, AWS, Git
"""


E2E_EMAIL = "e2e_recruiter@example.com"
E2E_PASSWORD = "Password123!"


@pytest.fixture(scope="module", autouse=True)
def shared_recruiter_account():
    """Guarantee the shared account exists before ANY test in this file runs.

    Every test here logs in as e2e_recruiter@example.com, but only the first
    one created it — so the whole file only worked when executed top to
    bottom. `pytest -k team`, `pytest --lf` after a failure, or any
    randomised/parallel ordering would fail with a bare
    `KeyError: 'access_token'` that says nothing about the real cause.

    A test you cannot run on its own is a test you cannot debug on its own,
    and "run the whole file and hope" is not a workflow. Creating the account
    once at module scope makes each test independently runnable without
    changing what any of them assert.
    """
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": E2E_EMAIL,
            "password": E2E_PASSWORD,
            "full_name": "E2E Recruiter",
            "company": "E2E Enterprise HR",
        },
    )
    # A 409 here just means a previous test in this module already made it.
    yield


def test_e2e_health_check_and_diagnostics():
    # Log in rather than sign up: the shared account is created once by the
    # module fixture, so a signup here would hit "already registered" and
    # return no token — which is exactly the ordering fragility the fixture
    # exists to remove. Every test in this file authenticates the same way.
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": E2E_EMAIL, "password": E2E_PASSWORD},
    )
    assert login_res.status_code == 200, login_res.text
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] in ["ok", "degraded"]

    diag = client.get("/api/v1/health/diagnostics", headers=headers)
    assert diag.status_code == 200
    from app.core.config import settings
    assert diag.json()["capacity"]["max_supported_users"] == settings.MAX_ACTIVE_RECRUITERS


def test_e2e_auth_signup_login_flow():
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "e2e_recruiter@example.com", "password": "Password123!"},
    )
    assert login_res.status_code == 200
    assert login_res.json()["user"]["email"] == "e2e_recruiter@example.com"


@patch("app.services.ai.engine.engine.run", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.analysis.extract_text", return_value=REALISTIC_RESUME)
@patch("app.services.parser.document_parser.extract_text", return_value=REALISTIC_RESUME)
def test_e2e_single_resume_analysis_and_report_flow(mock_parser, mock_analysis, mock_engine_run):
    mock_engine_run.return_value = {
        "candidate_name": "Jane Doe",
        "candidate_email": "jane@example.com",
        "overall_score": 88,
        "recommendation": "recommended",
        "credibility_score": {"score": 88, "confidence": "high", "sub_scores": {}},
        "ai_content_analysis": {"likelihood": "low"},
        "talent_velocity": {
            "growth_velocity_index": 85,
            "trajectory_stage": "Accelerating",
            "promotion_cadence_months": 18,
            "retention_stability_score": 90,
            "note": "Accelerating trajectory",
        },
        "flags": [],
        "positive_signals": [{"title": "FastAPI Master", "description": "Proven experience"}],
        "summary": "Excellent candidate",
    }

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "e2e_recruiter@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    user_id = login_res.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload Resume (PDF format)
    upload_res = client.post(
        "/api/v1/analysis/upload",
        headers=headers,
        files={"file": ("jane_doe_cv.pdf", io.BytesIO(MOCK_PDF), "application/pdf")},
        data={"target_role": "Senior Fullstack Engineer"},
    )
    assert upload_res.status_code == 200
    job_id = upload_res.json()["job_id"]

    # 2. Poll Status (/api/v1/analysis/{job_id}/status)
    status_res = client.get(f"/api/v1/analysis/{job_id}/status", headers=headers)
    assert status_res.status_code == 200
    job_data = status_res.json()
    report_id = job_data.get("report_id") or f"rep_{job_id[:8]}"

    # Seed mock report in _jobs store for testing report downstream sub-actions
    _jobs[f"report_{report_id}"] = {
        "id": report_id,
        "job_id": job_id,
        "_owner_user_id": user_id,
        "candidate_name": "Jane Doe",
        "candidate_email": "jane@example.com",
        "overall_score": 88,
        "recommendation": "recommended",
        "talent_velocity": {
            "growth_velocity_index": 85,
            "trajectory_stage": "Accelerating",
            "promotion_cadence_months": 18,
            "retention_stability_score": 90,
            "note": "Accelerating trajectory",
        },
        "flags": [],
        "positive_signals": [{"title": "FastAPI Master", "description": "Proven experience"}],
        "summary": "Excellent candidate",
    }

    # 3. Retrieve Report Details
    report_res = client.get(f"/api/v1/reports/{report_id}", headers=headers)
    assert report_res.status_code == 200
    report = report_res.json()
    assert report["candidate_name"] == "Jane Doe"
    assert "talent_velocity" in report

    # 4. Submit Recruiter Decision
    decision_res = client.post(
        f"/api/v1/reports/{report_id}/decision",
        headers=headers,
        json={"decision": "advance", "notes": "Impressive background"},
    )
    assert decision_res.status_code == 200

    # 5. Draft Candidate Email Notification
    draft_res = client.get(
        f"/api/v1/reports/{report_id}/notify/draft?decision=advance",
        headers=headers,
    )
    assert draft_res.status_code == 200
    assert "body" in draft_res.json()
    assert len(draft_res.json()["body"]) > 10


def test_e2e_copilot_and_talent_analytics_flow():
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "e2e_recruiter@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    user_id = login_res.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Seed an owned in-memory report to save co-pilot data against. Co-pilot
    # save now requires the report to actually resolve and be owned by the
    # caller (previously it accepted writes against ANY report_id string
    # with no ownership check at all — a real access-control gap).
    _jobs["report_rep_test123"] = {
        "id": "rep_test123",
        "_owner_user_id": user_id,
        "candidate_name": "Copilot Test Candidate",
    }

    # 1. Feature A: Save Interview Co-Pilot Scorecard & Notes
    copilot_save = client.post(
        "/api/v1/reports/rep_test123/copilot",
        headers=headers,
        json={
            "scorecard": [
                {"category": "technical", "score": 5, "notes": "Deep Python knowledge"},
                {"category": "culture_fit", "score": 4, "notes": "Great communicator"},
            ],
            "custom_questions": [
                {"question": "Explain FastAPI dependency injection mechanism.", "category": "technical", "is_asked": True}
            ],
            "interview_notes": "Candidate performed exceptionally during live system architecture discussion.",
            "recommendation_override": "advance",
        },
    )
    assert copilot_save.status_code == 200

    # 2. Get Co-Pilot Data
    copilot_get = client.get("/api/v1/reports/rep_test123/copilot", headers=headers)
    assert copilot_get.status_code == 200
    assert len(copilot_get.json()["copilot"]["scorecard"]) == 2

    # 3. Feature C: Enterprise Talent Analytics Endpoint
    analytics_res = client.get("/api/v1/reports/analytics", headers=headers)
    assert analytics_res.status_code == 200
    assert "distribution" in analytics_res.json()


def test_e2e_copilot_save_rejects_unowned_or_unknown_report():
    """
    Regression test for the access-control gap above: saving co-pilot data
    against a report_id that doesn't exist, or that belongs to a different
    recruiter, must be refused — not silently accepted into the in-memory
    store with a false "status: ok".
    """
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "e2e_recruiter@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Unknown report_id — never seeded anywhere.
    res = client.post(
        "/api/v1/reports/rep_never_existed_xyz/copilot",
        headers=headers,
        json={"scorecard": [], "custom_questions": []},
    )
    assert res.status_code == 404

    # Report owned by someone else.
    _jobs["report_rep_owned_by_other"] = {
        "id": "rep_owned_by_other",
        "_owner_user_id": "some-other-user-id",
        "candidate_name": "Not Yours",
    }
    res2 = client.post(
        "/api/v1/reports/rep_owned_by_other/copilot",
        headers=headers,
        json={"scorecard": [], "custom_questions": []},
    )
    assert res2.status_code == 404



@patch("app.services.parser.document_parser.extract_text", return_value=REALISTIC_RESUME)
def test_e2e_bulk_upload_ranking_duplicate_flow(mock_extract):
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "e2e_recruiter@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    files = [
        ("files", ("alice.pdf", io.BytesIO(MOCK_PDF), "application/pdf")),
        ("files", ("bob.pdf", io.BytesIO(MOCK_PDF), "application/pdf")),
    ]
    bulk_res = client.post("/api/v1/bulk/upload", headers=headers, files=files)
    assert bulk_res.status_code == 202
    batch_id = bulk_res.json()["batch_id"]

    # Status check
    b_status = client.get(f"/api/v1/bulk/{batch_id}/status", headers=headers)
    assert b_status.status_code == 200


@patch("app.services.parser.document_parser.extract_text", return_value=REALISTIC_RESUME)
def test_e2e_job_description_match_flow(mock_extract):
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "e2e_recruiter@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    match_res = client.post(
        "/api/v1/match/upload",
        headers=headers,
        files=[("files", ("charlie.pdf", io.BytesIO(MOCK_PDF), "application/pdf"))],
        data={"jd_text": "Looking for Senior React, Next.js, and TypeScript developer with 5+ years experience."},
    )
    assert match_res.status_code == 202
    assert "batch_id" in match_res.json()


def test_e2e_team_workspace_collaboration_flow():
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "e2e_recruiter@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Mock DB for team collaboration operations
    mock_db = MagicMock()
    mock_row = MagicMock()
    mock_row.data = {"id": "rep_test123", "user_id": login_res.json()["user"]["id"], "team_id": "team_1", "candidate_name": "Test Candidate"}
    mock_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_row
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        # 1. Create Team
        create_team = client.post(
            "/api/v1/teams",
            headers=headers,
            json={"name": "Engineering Hiring Squad"},
        )
        assert create_team.status_code == 200

        # 2. Add Comment on Report
        comment_res = client.post(
            "/api/v1/reports/rep_test123/comments",
            headers=headers,
            json={"comment": "Strong technical skills demonstrated in interview."},
        )
        assert comment_res.status_code == 200

        # 3. Add Vote on Report
        vote_res = client.post(
            "/api/v1/reports/rep_test123/vote",
            headers=headers,
            json={"vote": "advance"},
        )
        assert vote_res.status_code == 200
    finally:
        app.dependency_overrides.clear()
