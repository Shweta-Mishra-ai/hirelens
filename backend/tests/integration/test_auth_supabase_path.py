"""
Signing in when Supabase is the identity store.

Every auth test so far exercised the local SQLite fallback, because
SUPABASE_URL is unset under test. On a deployed instance Supabase is the
identity store — and `reports.user_id` is a foreign key into `auth.users`,
so an account that exists only locally can never own a row there.

That made the old fallbacks dangerous rather than resilient:

  * A signup whose Supabase call failed for any transient reason quietly
    created a local account instead. Its user id is not in `auth.users`, so
    every report it analysed failed to persist and fell back to the local
    SQLite file — which on an ephemeral disk is gone at the next restart,
    taking the account with it. The person is then unable to log in with a
    password they know is right.
  * A login that Supabase *rejected* fell through to the local store, so a
    stale password left behind in SQLite could beat the real one.

Supabase's answer now stands. Only an unreachable Supabase falls back.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_auth_client
from app.main import app
from app.services.teams import access
from tests.fake_supabase import AuthApiError, AuthRetryableError, FakeSupabase, FakeUser

client = TestClient(app)

CREDS = {"email": "sb_user@example.com", "password": "Password123!", "full_name": "Ess Bee"}


@pytest.fixture
def db():
    fake = FakeSupabase({"profiles": [], "teams": [], "team_members": [], "team_invites": []})
    # The same fake stands in for both clients. In production they are
    # deliberately different objects — signing in on the shared
    # service-role client silently hands the whole process to that user
    # (see test_shared_client_not_hijacked.py). What matters here is the
    # behaviour against a Supabase that answers, so one fake is right.
    app.dependency_overrides[get_db] = lambda: fake
    app.dependency_overrides[get_auth_client] = lambda: fake
    access._mem_teams.clear()
    access._mem_team_members.clear()
    access._mem_team_invites.clear()
    yield fake
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_auth_client, None)


class TestSignup:
    def test_an_account_is_created_in_supabase_not_locally(self, db):
        from app.core import local_db

        res = client.post("/api/v1/auth/signup", json=CREDS)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["access_token"]
        assert body["user"]["email"] == CREDS["email"]
        assert CREDS["email"] in db.auth.users
        # Nothing was written to the local store — Supabase owns this account.
        assert local_db.get_user_by_email(CREDS["email"]) is None

    def test_the_profile_row_is_created_so_the_name_resolves(self, db):
        client.post("/api/v1/auth/signup", json=CREDS)
        profile = next(p for p in db.tables["profiles"] if p["email"] == CREDS["email"])
        assert profile["full_name"] == "Ess Bee"

    def test_a_duplicate_address_is_a_conflict_not_a_new_local_account(self, db):
        from app.core import local_db

        client.post("/api/v1/auth/signup", json=CREDS)
        res = client.post("/api/v1/auth/signup", json=CREDS)
        assert res.status_code == 409
        assert res.json()["error"] == "conflict"
        assert local_db.get_user_by_email(CREDS["email"]) is None

    def test_supabase_being_down_fails_the_signup_rather_than_forking_the_identity(self, db):
        """The heart of it: a shadow local account would get a user id that
        `auth.users` has never heard of, so nothing it creates can persist."""
        from app.core import local_db

        db.auth.raises = AuthRetryableError("connection refused")
        res = client.post("/api/v1/auth/signup", json=CREDS)
        assert res.status_code == 503
        assert res.json()["error"] == "account_store_unavailable"
        assert "try again" in res.json()["message"].lower()
        assert local_db.get_user_by_email(CREDS["email"]) is None

    def test_an_unexpected_supabase_error_also_fails_rather_than_forking(self, db):
        from app.core import local_db

        db.auth.raises = AuthApiError("database is starting up", status=500)
        res = client.post("/api/v1/auth/signup", json=CREDS)
        assert res.status_code == 503
        assert local_db.get_user_by_email(CREDS["email"]) is None

    def test_email_confirmation_is_reported_rather_than_faked(self, db):
        def sign_up(credentials):
            from tests.fake_supabase import FakeAuthResult

            return FakeAuthResult(None)

        db.auth.sign_up = sign_up
        res = client.post("/api/v1/auth/signup", json=CREDS)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["requires_email_confirmation"] is True
        assert body["access_token"] is None


class TestLogin:
    def test_a_supabase_account_can_sign_in(self, db):
        client.post("/api/v1/auth/signup", json=CREDS)
        res = client.post(
            "/api/v1/auth/login", json={"email": CREDS["email"], "password": CREDS["password"]}
        )
        assert res.status_code == 200, res.text
        assert res.json()["user"]["full_name"] == "Ess Bee"

    def test_a_wrong_password_is_refused(self, db):
        client.post("/api/v1/auth/signup", json=CREDS)
        res = client.post(
            "/api/v1/auth/login", json={"email": CREDS["email"], "password": "WrongPassword1!"}
        )
        assert res.status_code == 401

    def test_a_stale_local_password_cannot_beat_supabase(self, db, fresh_local_db):
        """Supabase says no. The local store must not say yes."""
        fresh_local_db.create_user(CREDS["email"], "OldPassword123!", "Ess Bee")
        client.post("/api/v1/auth/signup", json=CREDS)

        res = client.post(
            "/api/v1/auth/login", json={"email": CREDS["email"], "password": "OldPassword123!"}
        )
        assert res.status_code == 401, res.text

    def test_an_unreachable_supabase_still_lets_a_local_account_in(self, db, fresh_local_db):
        """The other half: locking everyone out during an outage is worse
        than checking the store that predates it."""
        fresh_local_db.create_user("legacy@example.com", "Password123!", "Legacy Person")
        db.auth.raises = AuthRetryableError("connection refused")

        res = client.post(
            "/api/v1/auth/login", json={"email": "legacy@example.com", "password": "Password123!"}
        )
        assert res.status_code == 200, res.text
        assert res.json()["user"]["full_name"] == "Legacy Person"

    def test_an_unconfirmed_address_says_so(self, db):
        db.auth.raises = AuthApiError("Email not confirmed", status=400)
        res = client.post(
            "/api/v1/auth/login", json={"email": CREDS["email"], "password": CREDS["password"]}
        )
        assert res.status_code == 401
        assert "confirm" in res.json()["message"].lower()

    def test_an_unknown_address_is_refused(self, db):
        res = client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "Password123!"}
        )
        assert res.status_code == 401


class TestGoogleSignIn:
    def test_a_valid_supabase_session_is_exchanged_for_a_hirelens_token(self, db):
        user = FakeUser("sb-google-1", "g@example.com", {"full_name": "Goo Gle", "company": "Acme"})
        db.auth.sessions["good-token"] = user

        res = client.post("/api/v1/auth/oauth-verify", json={"access_token": "good-token"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["access_token"]
        assert body["user"]["email"] == "g@example.com"
        assert body["user"]["full_name"] == "Goo Gle"

    def test_the_issued_token_actually_works(self, db):
        db.auth.sessions["good-token"] = FakeUser("sb-google-1", "g@example.com", {"name": "Goo Gle"})
        token = client.post(
            "/api/v1/auth/oauth-verify", json={"access_token": "good-token"}
        ).json()["access_token"]

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email"] == "g@example.com"

    def test_the_google_name_is_read_from_either_metadata_key(self, db):
        db.auth.sessions["t"] = FakeUser("sb-g", "g@example.com", {"name": "Only Name"})
        body = client.post("/api/v1/auth/oauth-verify", json={"access_token": "t"}).json()
        assert body["user"]["full_name"] == "Only Name"

    @pytest.mark.parametrize("token", ["", " ", "garbage", "a.b.c", "null", "x" * 4000])
    def test_a_token_supabase_does_not_recognise_is_refused(self, db, token):
        """This endpoint used to mint a valid 7-day session for any string at
        all. There is no fallback here on purpose."""
        res = client.post("/api/v1/auth/oauth-verify", json={"access_token": token})
        assert res.status_code == 401
        assert "access_token" not in res.json()

    def test_supabase_being_unreachable_does_not_mint_a_token(self, db):
        db.auth.raises = AuthRetryableError("connection refused")
        res = client.post("/api/v1/auth/oauth-verify", json={"access_token": "anything"})
        assert res.status_code == 401
        assert "access_token" not in res.json()

    def test_signing_in_with_google_accepts_a_pending_team_invite(self, db):
        db.tables["team_invites"] = [
            {"id": "inv-1", "team_id": "t1", "email": "g@example.com", "status": "pending"},
        ]
        db.auth.sessions["good-token"] = FakeUser("sb-google-1", "g@example.com", {})

        res = client.post("/api/v1/auth/oauth-verify", json={"access_token": "good-token"})
        assert res.status_code == 200, res.text
        assert any(
            m["user_id"] == "sb-google-1" and m["team_id"] == "t1"
            for m in db.tables.get("team_members", [])
        )
