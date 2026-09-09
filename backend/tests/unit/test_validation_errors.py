"""
HireLens — Validation error shape tests
Run: cd backend && python -m pytest tests/unit/test_validation_errors.py -v

FastAPI's default 422 body is `{"detail": [{"loc": [...], "msg": ...}]}`.
The frontend's API client (frontend/src/lib/api.ts) reads `error` and
`message` off the body and falls back to "Server error 422" when they are
absent — so before this handler existed, every validation failure surfaced in
the UI as a bare "Server error 422" with no indication of what to fix.

That lands hardest on the signup form: it is the first screen anyone sees,
and it has the most validation on it (name length, password rules, email
format). "Server error" on a first signup attempt reads as "this product is
broken", not "your password is too short".
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_validation_error_uses_the_standard_error_shape():
    res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "shape@example.com",
            "password": "Password123!",
            "full_name": "X",  # too short
            "company": "Co",
        },
    )

    assert res.status_code == 422
    body = res.json()
    # The three keys every other error in this API returns.
    assert body["error"] == "validation_error"
    assert "request_id" in body
    # And a message the frontend can actually render.
    assert "message" in body
    assert body["message"] != ""
    assert "Server error" not in body["message"]


def test_validation_message_names_the_offending_field():
    res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "field@example.com",
            "password": "Password123!",
            "full_name": "X",
            "company": "Co",
        },
    )

    body = res.json()
    assert "full_name" in body["message"]
    assert "2 characters" in body["message"]
    # Structured form too, for a client that wants to highlight the input.
    assert body["details"][0]["field"] == "full_name"


def test_validation_strips_pydantic_value_error_prefix():
    """Pydantic prefixes custom validator messages with 'Value error, ' —
    an implementation detail no user should ever read."""
    res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "prefix@example.com",
            "password": "Password123!",
            "full_name": "X",
            "company": "Co",
        },
    )

    assert "Value error" not in res.json()["message"]


def test_malformed_email_is_reported_as_a_validation_error():
    res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "not-an-email",
            "password": "Password123!",
            "full_name": "Real Name",
            "company": "Co",
        },
    )

    assert res.status_code == 422
    body = res.json()
    assert body["error"] == "validation_error"
    assert body["details"][0]["field"] == "email"


def test_missing_required_field_is_reported_with_its_name():
    res = client.post("/api/v1/auth/login", json={"email": "someone@example.com"})

    assert res.status_code == 422
    body = res.json()
    assert body["error"] == "validation_error"
    assert "password" in body["message"]
