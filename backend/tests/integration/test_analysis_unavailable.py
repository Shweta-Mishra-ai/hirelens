"""
Tests for upload behaviour when no AI provider is configured.

Previously every upload endpoint accepted the file, created a job, and let a
background task discover the problem ~15 seconds later. The user saw the full
progress animation and then this, verbatim:

    AI analysis failed: No LLM API key configured. Set GEMINI_API_KEY
    (free at aistudio.google.com) in your .env file.

That is operator advice shown to a recruiter, after the upload was already
paid for. The condition depends only on configuration, so it is now checked
before the file is read.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)

MOCK_PDF = b"%PDF-1.4\n" + b"0" * 400


@pytest.fixture
def no_llm_configured(monkeypatch):
    """Simulate a server with no AI provider set up at all."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "", raising=False)


@pytest.fixture
def auth_headers():
    """
    A signed-in recruiter.

    Signup is attempted first and falls back to login: the SQLite store lives
    for the whole session, so the second test to use this fixture would
    otherwise get a 409 and no token.
    """
    creds = {"email": "unavailable@example.com", "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "Unavailable Tester"})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_single_upload_is_refused_up_front(no_llm_configured, auth_headers):
    res = client.post(
        "/api/v1/analysis/upload",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(MOCK_PDF), "application/pdf")},
    )
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "analysis_unavailable"
    # No job was created, so there is nothing to poll.
    assert "job_id" not in body


def test_refusal_says_the_file_was_not_uploaded(no_llm_configured, auth_headers):
    res = client.post(
        "/api/v1/analysis/upload",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(MOCK_PDF), "application/pdf")},
    )
    assert "was not uploaded" in res.json()["message"]


def test_refusal_does_not_leak_operator_configuration_advice(no_llm_configured, auth_headers):
    """A recruiter cannot act on ".env" or "GEMINI_API_KEY"."""
    res = client.post(
        "/api/v1/analysis/upload",
        headers=auth_headers,
        files={"file": ("cv.pdf", io.BytesIO(MOCK_PDF), "application/pdf")},
    )
    message = res.json()["message"]
    for leak in ["GEMINI_API_KEY", ".env", "aistudio", "GROQ", "ANTHROPIC"]:
        assert leak not in message
    assert "administrator" in message.lower()


def test_bulk_upload_is_refused_up_front(no_llm_configured, auth_headers):
    res = client.post(
        "/api/v1/bulk/upload",
        headers=auth_headers,
        files=[("files", ("a.pdf", io.BytesIO(MOCK_PDF), "application/pdf"))],
    )
    assert res.status_code == 503
    assert res.json()["error"] == "analysis_unavailable"


def test_jd_match_upload_is_refused_up_front(no_llm_configured, auth_headers):
    res = client.post(
        "/api/v1/match/upload",
        headers=auth_headers,
        data={"jd_text": "We need a senior backend engineer with Go and Kafka experience."},
        files=[("files", ("a.pdf", io.BytesIO(MOCK_PDF), "application/pdf"))],
    )
    assert res.status_code == 503
    assert res.json()["error"] == "analysis_unavailable"


def test_uploads_are_accepted_once_any_provider_is_configured(monkeypatch, auth_headers):
    """Any one of the three providers is enough to accept the upload."""
    for provider in ["GEMINI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"]:
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "", raising=False)
        monkeypatch.setattr(settings, "GROQ_API_KEY", "", raising=False)
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "", raising=False)
        monkeypatch.setattr(settings, provider, "configured", raising=False)

        res = client.post(
            "/api/v1/analysis/upload",
            headers=auth_headers,
            files={"file": ("cv.pdf", io.BytesIO(MOCK_PDF), "application/pdf")},
        )
        assert res.status_code == 200, f"{provider} alone should be enough"
        assert "job_id" in res.json()


def test_health_reports_analysis_readiness(no_llm_configured):
    """The frontend needs a way to warn before the user picks a file."""
    body = client.get("/api/v1/health").json()
    assert body["llm_ready"] is False
