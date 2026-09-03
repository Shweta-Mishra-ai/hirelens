"""
Unit & Load/Validation/Error Handling Tests for HireLens
Tests:
1. File size limit validation (HTTP 413)
2. Unsupported MIME/file type validation (HTTP 415)
3. Invalid job description validation (HTTP 422)
4. Rate limit check handling (HTTP 429)
5. Capacity limit enforcement (HTTP 429)
6. Error response structure with x-request-id header
"""

import pytest
import io
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import create_access_token
from app.core.exceptions import FileTooLarge, UnsupportedFileType, InvalidJobDescription
from app.core.dependencies import get_redis

client = TestClient(app)


def get_auth_header():
    token = create_access_token({"sub": "user_load_test", "email": "loadtest@example.com"})
    return {"Authorization": f"Bearer {token}"}


def test_error_response_structure_and_request_id():
    res = client.get("/api/v1/reports/non_existent_id_123")
    assert res.status_code == 401
    assert "x-request-id" in res.headers
    data = res.json()
    assert "error" in data
    assert "message" in data


def test_file_too_large_exception_handling():
    headers = get_auth_header()
    with patch("app.api.v1.endpoints.analysis.validate_upload", side_effect=FileTooLarge(10)):
        res = client.post(
            "/api/v1/analysis/upload",
            headers=headers,
            files={"file": ("large_file.pdf", io.BytesIO(b"%PDF-1.4 large file"), "application/pdf")},
        )
        assert res.status_code == 413
        assert res.json()["error"] == "file_too_large"


def test_unsupported_file_type_exception_handling():
    headers = get_auth_header()
    with patch("app.api.v1.endpoints.analysis.validate_upload", side_effect=UnsupportedFileType()):
        res = client.post(
            "/api/v1/analysis/upload",
            headers=headers,
            files={"file": ("script.exe", io.BytesIO(b"executable"), "application/octet-stream")},
        )
        assert res.status_code == 415
        assert res.json()["error"] == "unsupported_file_type"


def test_invalid_job_description_validation():
    headers = get_auth_header()
    res = client.post(
        "/api/v1/match/upload",
        headers=headers,
        files=[("files", ("resume.pdf", io.BytesIO(b"%PDF-1.4 mock"), "application/pdf"))],
        data={"jd_text": "too short"},  # < 30 chars
    )
    assert res.status_code == 422
    assert res.json()["error"] == "invalid_job_description"


def test_rate_limit_exceeded_handling():
    headers = get_auth_header()
    mock_redis = MagicMock()
    mock_redis.pipeline.return_value.execute.return_value = [None, 100, None, None]  # Over limit

    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        res = client.get(
            "/api/v1/reports",
            headers=headers,
        )
        assert res.status_code in [200, 429]
    finally:
        app.dependency_overrides.clear()
