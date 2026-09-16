"""
HireLens — Forgetting your password and getting back in

The whole point of this flow is that it is the only way back into an account
once the password is gone, so every step of it has to actually work. These
cover both storage paths: Supabase, which sends and verifies its own recovery
link, and the local store, which mints one itself because there is no provider
to do it.

Run: cd backend && python -m pytest tests/integration/test_password_reset.py -v
"""
import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth as auth_ep
from app.core import local_db
from app.core.dependencies import get_db
from app.main import app
from tests.fake_supabase import FakeSupabase, AuthApiError, AuthRetryableError, FakeUser

client = TestClient(app)


@pytest.fixture
def mailer(monkeypatch):
    """Capture the reset emails instead of sending them."""
    sent = []

    async def fake_send(to_email, reset_url, ttl_minutes):
        sent.append({"to": to_email, "url": reset_url, "ttl": ttl_minutes})
        return True

    monkeypatch.setattr(auth_ep, "send_password_reset_email", fake_send)
    return sent


@pytest.fixture
def supabase():
    fake = FakeSupabase({"profiles": [], "reports": []})
    app.dependency_overrides[get_db] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_db, None)


def _token_from(url: str) -> str:
    from urllib.parse import urlparse, parse_qs

    return parse_qs(urlparse(url).query)["token"][0]


# ── The local store ─────────────────────────────────────────────────────────
class TestLocalResetRoundTrip:
    def test_a_forgotten_password_can_be_replaced_and_used(self, mailer):
        creds = {"email": "forgetful@example.com", "password": "OriginalPass123!"}
        signup = client.post(
            "/api/v1/auth/signup", json={**creds, "full_name": "For Getful"}
        )
        assert signup.status_code in (200, 409), signup.text

        asked = client.post("/api/v1/auth/forgot-password", json={"email": creds["email"]})
        assert asked.status_code == 200
        assert len(mailer) == 1

        token = _token_from(mailer[0]["url"])
        reset = client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": token, "new_password": "BrandNewPass456!"},
        )
        assert reset.status_code == 200, reset.text

        # The old password is dead...
        old = client.post("/api/v1/auth/login", json=creds)
        assert old.status_code == 401

        # ...and the new one works.
        new = client.post(
            "/api/v1/auth/login",
            json={"email": creds["email"], "password": "BrandNewPass456!"},
        )
        assert new.status_code == 200, new.text
        assert new.json()["user"]["email"] == creds["email"]

    def test_the_link_points_at_a_page_that_exists(self, mailer):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "linkcheck@example.com", "password": "OriginalPass123!", "full_name": "Link Check"},
        )
        client.post("/api/v1/auth/forgot-password", json={"email": "linkcheck@example.com"})
        assert "/reset-password" in mailer[0]["url"]

    def test_a_token_works_once(self, mailer):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "onceonly@example.com", "password": "OriginalPass123!", "full_name": "Once Only"},
        )
        client.post("/api/v1/auth/forgot-password", json={"email": "onceonly@example.com"})
        token = _token_from(mailer[0]["url"])

        first = client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": token, "new_password": "FirstNewPass123!"},
        )
        assert first.status_code == 200

        replay = client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": token, "new_password": "AttackerPass123!"},
        )
        assert replay.status_code == 401

        # And the attacker's password never took.
        assert client.post(
            "/api/v1/auth/login",
            json={"email": "onceonly@example.com", "password": "AttackerPass123!"},
        ).status_code == 401

    def test_asking_again_invalidates_the_first_link(self, mailer):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "twice@example.com", "password": "OriginalPass123!", "full_name": "Twice Over"},
        )
        client.post("/api/v1/auth/forgot-password", json={"email": "twice@example.com"})
        client.post("/api/v1/auth/forgot-password", json={"email": "twice@example.com"})

        stale = _token_from(mailer[0]["url"])
        fresh = _token_from(mailer[1]["url"])
        assert stale != fresh

        assert client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": stale, "new_password": "FromStaleLink123!"},
        ).status_code == 401
        assert client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": fresh, "new_password": "FromFreshLink123!"},
        ).status_code == 200

    def test_a_made_up_token_is_refused(self):
        assert client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": "not-a-real-token", "new_password": "Whatever123!"},
        ).status_code == 401

    def test_an_expired_token_is_refused(self, mailer):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "expired@example.com", "password": "OriginalPass123!", "full_name": "Ex Pired"},
        )
        client.post("/api/v1/auth/forgot-password", json={"email": "expired@example.com"})
        token = _token_from(mailer[0]["url"])

        # Age the token past its lifetime.
        from datetime import datetime, timedelta, timezone

        with local_db._get_connection() as conn:
            conn.execute(
                "UPDATE password_resets SET expires_at = ?",
                ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),),
            )
            conn.commit()

        refused = client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": token, "new_password": "TooLate123!"},
        )
        assert refused.status_code == 401
        assert "expired" in refused.json()["message"].lower()

    def test_the_raw_token_is_never_stored(self, mailer):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "hashed@example.com", "password": "OriginalPass123!", "full_name": "Hash Ed"},
        )
        client.post("/api/v1/auth/forgot-password", json={"email": "hashed@example.com"})
        token = _token_from(mailer[0]["url"])

        with local_db._get_connection() as conn:
            rows = conn.execute("SELECT token_hash FROM password_resets").fetchall()
        stored = {r["token_hash"] for r in rows}
        assert token not in stored, "a leaked database file would hand over working reset tokens"
        assert all(len(h) == 64 for h in stored)

    def test_a_short_password_is_refused_before_the_token_is_spent(self, mailer):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "shortpw@example.com", "password": "OriginalPass123!", "full_name": "Short Pw"},
        )
        client.post("/api/v1/auth/forgot-password", json={"email": "shortpw@example.com"})
        token = _token_from(mailer[0]["url"])

        assert client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": token, "new_password": "short"},
        ).status_code == 422

        # The token survived, so the user can try again with a longer one.
        assert client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": token, "new_password": "LongEnoughPass123!"},
        ).status_code == 200


class TestForgotPasswordRevealsNothing:
    def test_an_unknown_address_gets_the_same_answer(self, mailer):
        known = client.post(
            "/api/v1/auth/signup",
            json={"email": "known@example.com", "password": "OriginalPass123!", "full_name": "Kno Wn"},
        )
        assert known.status_code in (200, 409)

        a = client.post("/api/v1/auth/forgot-password", json={"email": "known@example.com"})
        b = client.post("/api/v1/auth/forgot-password", json={"email": "nobody-here@example.com"})

        assert a.status_code == b.status_code == 200
        assert a.json() == b.json()
        # ...and no email went to the address that has no account.
        assert [m["to"] for m in mailer] == ["known@example.com"]

    def test_the_address_is_matched_case_insensitively(self, mailer):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "mixedcase@example.com", "password": "OriginalPass123!", "full_name": "Mix Ed"},
        )
        client.post("/api/v1/auth/forgot-password", json={"email": "MixedCase@Example.com"})
        assert [m["to"] for m in mailer] == ["mixedcase@example.com"]


# ── Supabase ────────────────────────────────────────────────────────────────
class TestSupabaseReset:
    def test_the_reset_email_points_at_the_reset_page(self, supabase):
        supabase.auth.users["user@example.com"] = ("OriginalPass123!", FakeUser("sb-1", "user@example.com"))

        res = client.post("/api/v1/auth/forgot-password", json={"email": "user@example.com"})
        assert res.status_code == 200

        assert len(supabase.auth.reset_emails) == 1
        sent = supabase.auth.reset_emails[0]
        assert sent["email"] == "user@example.com"
        # Without redirect_to, Supabase sends the recovery token to the
        # project's Site URL, where nothing reads it and the user is stuck.
        assert sent["options"]["redirect_to"].endswith("/reset-password")

    def test_a_recovery_token_sets_the_new_password(self, supabase):
        user = FakeUser("sb-1", "user@example.com")
        supabase.auth.users["user@example.com"] = ("OriginalPass123!", user)
        supabase.auth.sessions["recovery-token-abc"] = user

        res = client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": "recovery-token-abc", "new_password": "BrandNewPass456!"},
        )
        assert res.status_code == 200, res.text
        assert supabase.auth.users["user@example.com"][0] == "BrandNewPass456!"

    def test_the_new_password_then_signs_them_in(self, supabase):
        user = FakeUser("sb-1", "user@example.com")
        supabase.auth.users["user@example.com"] = ("OriginalPass123!", user)
        supabase.auth.sessions["recovery-token-abc"] = user

        client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": "recovery-token-abc", "new_password": "BrandNewPass456!"},
        )

        assert client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "OriginalPass123!"},
        ).status_code == 401
        assert client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "BrandNewPass456!"},
        ).status_code == 200

    def test_an_unknown_recovery_token_is_refused(self, supabase):
        res = client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": "never-issued", "new_password": "BrandNewPass456!"},
        )
        assert res.status_code == 401
        assert "expired" in res.json()["message"].lower() or "used" in res.json()["message"].lower()

    def test_an_expired_link_says_to_request_another(self, supabase):
        supabase.auth.raises = AuthApiError("Email link is invalid or has expired", 401, "otp_expired")
        res = client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": "stale", "new_password": "BrandNewPass456!"},
        )
        assert res.status_code == 401
        assert "new one" in res.json()["message"].lower()

    def test_a_breached_password_is_explained_not_reported_as_an_outage(self, supabase, monkeypatch):
        user = FakeUser("sb-1", "user@example.com")
        supabase.auth.users["user@example.com"] = ("OriginalPass123!", user)
        supabase.auth.sessions["recovery-token-abc"] = user

        def refuse(uid, attributes):
            raise AuthApiError(
                "Password is known to be weak and easy to guess, please choose a different one.",
                422,
                "weak_password",
            )

        monkeypatch.setattr(supabase.auth.admin, "update_user_by_id", refuse)

        res = client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": "recovery-token-abc", "new_password": "Password123!"},
        )
        assert res.status_code == 422
        assert "breach" in res.json()["message"].lower()

    def test_an_unreachable_supabase_is_a_503_not_a_bad_token(self, supabase):
        supabase.auth.raises = AuthRetryableError("connection failed", 0)
        res = client.post(
            "/api/v1/auth/reset-password",
            json={"access_token": "whatever", "new_password": "BrandNewPass456!"},
        )
        assert res.status_code == 503
