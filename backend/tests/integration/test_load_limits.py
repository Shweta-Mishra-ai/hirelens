"""
Load-handling limits.

The regression that motivated this file: bulk and JD-match upload read every
file fully into memory and only then compared the total against
BULK_MAX_TOTAL_MB. With BULK_MAX_FILES=50 and MAX_FILE_SIZE_MB=10, a caller
could push ~500MB of request body into a 512MB instance before the 150MB cap
was ever evaluated — the process was OOM-killed before it could reject
anything. The cap is now enforced as the bytes arrive.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def _pdf(size_bytes: int) -> bytes:
    """A magic-byte-valid PDF padded to an exact size."""
    head = b"%PDF-1.4\n"
    return head + b"0" * max(0, size_bytes - len(head))


@pytest.fixture
def headers():
    creds = {"email": "loadtest@example.com", "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "Load Tester"})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def small_caps(monkeypatch):
    """
    Shrink the limits so the test exercises the guard without allocating
    hundreds of megabytes in CI.
    """
    monkeypatch.setattr(settings, "BULK_MAX_TOTAL_MB", 2, raising=False)
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1, raising=False)


class TestBulkTotalSize:
    def test_batch_over_the_total_cap_is_rejected(self, headers, small_caps):
        # 4 x 1MB against a 2MB cap.
        files = [
            ("files", (f"cv{i}.pdf", io.BytesIO(_pdf(1024 * 1024)), "application/pdf"))
            for i in range(4)
        ]
        res = client.post("/api/v1/bulk/upload", headers=headers, files=files)
        assert res.status_code == 413
        assert res.json()["error"] == "file_too_large"

    def test_rejection_leaves_no_orphaned_jobs(self, headers, small_caps):
        from app.api.v1.endpoints.analysis import _jobs

        before = len(_jobs)
        files = [
            ("files", (f"cv{i}.pdf", io.BytesIO(_pdf(1024 * 1024)), "application/pdf"))
            for i in range(4)
        ]
        client.post("/api/v1/bulk/upload", headers=headers, files=files)
        # Every job created during the aborted read must be rolled back —
        # otherwise the store grows on every rejected batch.
        assert len(_jobs) == before

    def test_batch_within_the_cap_is_accepted(self, headers, small_caps):
        files = [
            ("files", (f"cv{i}.pdf", io.BytesIO(_pdf(400 * 1024)), "application/pdf"))
            for i in range(2)
        ]
        res = client.post("/api/v1/bulk/upload", headers=headers, files=files)
        # 202: the batch is queued and analysed in the background.
        assert res.status_code == 202, res.text
        assert res.json()["accepted"] >= 1

    def test_file_count_cap_is_enforced(self, headers):
        files = [
            ("files", (f"cv{i}.pdf", io.BytesIO(_pdf(1024)), "application/pdf"))
            for i in range(settings.BULK_MAX_FILES + 5)
        ]
        res = client.post("/api/v1/bulk/upload", headers=headers, files=files)
        assert res.status_code == 413
        assert res.json()["error"] == "too_many_files"

    def test_empty_batch_is_rejected(self, headers):
        res = client.post("/api/v1/bulk/upload", headers=headers, files=[])
        assert res.status_code in (422, 413)

    def test_batch_of_only_invalid_files_is_rejected(self, headers):
        files = [
            ("files", ("notes.txt", io.BytesIO(b"just text"), "text/plain")),
            ("files", ("image.png", io.BytesIO(b"\x89PNG\r\n"), "image/png")),
        ]
        res = client.post("/api/v1/bulk/upload", headers=headers, files=files)
        assert res.status_code == 422
        assert res.json()["error"] == "empty_batch"


class TestJdMatchTotalSize:
    def test_batch_over_the_total_cap_is_rejected(self, headers, small_caps):
        files = [
            ("files", (f"cv{i}.pdf", io.BytesIO(_pdf(1024 * 1024)), "application/pdf"))
            for i in range(4)
        ]
        res = client.post(
            "/api/v1/match/upload",
            headers=headers,
            data={"jd_text": "Senior backend engineer with Go, Kafka and Kubernetes experience."},
            files=files,
        )
        assert res.status_code == 413

    def test_short_job_description_is_rejected(self, headers):
        res = client.post(
            "/api/v1/match/upload",
            headers=headers,
            data={"jd_text": "too short"},
            files=[("files", ("cv.pdf", io.BytesIO(_pdf(2048)), "application/pdf"))],
        )
        assert res.status_code == 422


class TestSingleFileLimits:
    def test_file_over_the_single_file_cap_is_rejected(self, headers, small_caps):
        res = client.post(
            "/api/v1/analysis/upload",
            headers=headers,
            files={"file": ("big.pdf", io.BytesIO(_pdf(2 * 1024 * 1024)), "application/pdf")},
        )
        assert res.status_code == 413
        assert res.json()["error"] == "file_too_large"

    def test_empty_file_is_rejected(self, headers):
        res = client.post(
            "/api/v1/analysis/upload",
            headers=headers,
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        )
        assert res.status_code == 415

    @pytest.mark.parametrize(
        "name,content,mime",
        [
            ("resume.exe", b"MZ\x90\x00", "application/octet-stream"),
            ("resume.pdf", b"MZ\x90\x00 not really a pdf", "application/pdf"),
            ("resume.docx", b"not a zip archive at all", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("resume.sh", b"#!/bin/bash\nrm -rf /", "text/x-shellscript"),
        ],
    )
    def test_magic_byte_mismatch_is_rejected(self, headers, name, content, mime):
        """An honest extension is not enough — the header must match."""
        res = client.post(
            "/api/v1/analysis/upload",
            headers=headers,
            files={"file": (name, io.BytesIO(content), mime)},
        )
        assert res.status_code == 415


class TestErrorEnvelope:
    """Every error must carry the documented shape, including a trace id."""

    @pytest.mark.parametrize(
        "method,path,kwargs",
        [
            ("get", "/api/v1/reports/missing", {}),
            ("get", "/api/v1/no-such-route", {}),
            ("post", "/api/v1/auth/signup", {"json": {}}),
            ("post", "/api/v1/auth/login", {"json": {"email": "bad", "password": "x"}}),
        ],
    )
    def test_error_responses_use_the_standard_envelope(self, headers, method, path, kwargs):
        res = getattr(client, method)(path, headers=headers, **kwargs)
        assert res.status_code >= 400
        body = res.json()
        assert "error" in body and isinstance(body["error"], str)
        assert "message" in body and body["message"].strip()
        assert "request_id" in body
        # FastAPI's raw shape must never reach a client.
        assert not isinstance(body.get("detail"), list)

    def test_validation_message_is_human_readable(self, headers):
        res = client.post("/api/v1/auth/signup", json={})
        body = res.json()
        assert body["error"] == "validation_error"
        assert "required" in body["message"].lower()
        # Structured detail is still available for programmatic clients.
        assert isinstance(body.get("details"), list)

    def test_unknown_route_explains_itself(self):
        body = client.get("/api/v1/nope").json()
        assert body["error"] == "not_found"
        assert "endpoint" in body["message"].lower()

    def test_every_response_carries_a_request_id_header(self):
        res = client.get("/api/v1/health")
        assert res.headers.get("x-request-id")
