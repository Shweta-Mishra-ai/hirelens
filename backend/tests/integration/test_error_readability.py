"""
Whatever the server says, the app has to be able to read it.

CORS used to be registered before the two http middlewares, which put the
catch-all in request_middleware OUTSIDE it rather than inside. A 500 was
therefore returned with no Access-Control-Allow-Origin header, and the
browser refused to hand the response to the app — so from the frontend a
server error looked identical to the API being unreachable: no status, no
message, just a failed fetch and a silent empty page with no way to tell
the user what happened.
"""

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

ORIGIN = "http://localhost:3000"

_router = APIRouter()


@_router.get("/boom")
async def _boom():
    raise RuntimeError("something nobody anticipated")


app.include_router(_router, prefix="/api/v1/__test")

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def allow_origin(monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", ORIGIN, raising=False)


class TestErrorsCarryCorsHeaders:
    def test_an_unhandled_error_is_readable_by_the_browser(self):
        res = client.get("/api/v1/__test/boom", headers={"Origin": ORIGIN})
        assert res.status_code == 500
        assert res.headers.get("access-control-allow-origin") == ORIGIN
        body = res.json()
        assert body["error"] == "internal_error"
        assert body["message"]
        assert body["request_id"]

    def test_the_error_body_does_not_leak_internals(self):
        res = client.get("/api/v1/__test/boom", headers={"Origin": ORIGIN})
        text = res.text
        assert "something nobody anticipated" not in text
        assert "Traceback" not in text
        assert "RuntimeError" not in text

    def test_a_404_is_readable(self):
        res = client.get("/api/v1/does-not-exist", headers={"Origin": ORIGIN})
        assert res.status_code == 404
        assert res.headers.get("access-control-allow-origin") == ORIGIN

    def test_a_validation_error_is_readable(self):
        res = client.post("/api/v1/auth/login", json={}, headers={"Origin": ORIGIN})
        assert res.status_code == 422
        assert res.headers.get("access-control-allow-origin") == ORIGIN
        assert res.json()["message"]

    def test_an_auth_error_is_readable(self):
        res = client.get("/api/v1/reports", headers={"Origin": ORIGIN, "Authorization": "Bearer nope"})
        assert res.status_code == 401
        assert res.headers.get("access-control-allow-origin") == ORIGIN

    def test_a_success_still_carries_the_trace_headers(self):
        res = client.get("/api/v1/health", headers={"Origin": ORIGIN})
        assert res.status_code == 200
        assert res.headers.get("access-control-allow-origin") == ORIGIN
        assert res.headers.get("x-request-id")
        assert res.headers.get("x-response-time")

    def test_security_headers_survive_the_reordering(self):
        res = client.get("/api/v1/health", headers={"Origin": ORIGIN})
        assert res.headers["x-content-type-options"] == "nosniff"
        assert res.headers["x-frame-options"] == "DENY"

    def test_an_origin_that_is_not_allowed_gets_no_header(self):
        res = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
        assert res.headers.get("access-control-allow-origin") != "https://evil.example"
