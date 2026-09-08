"""
HireLens — token revocation tests
Run: cd backend && python -m pytest tests/unit/test_token_revocation.py -v

The gap these close: signing out did not sign you out.

A JWT is self-contained, so validating the signature and the expiry was the
whole check. `POST /auth/logout` cleared the cookie and the frontend dropped
its copy, but the token STRING stayed a working credential for the rest of
its lifetime — up to seven days. Anyone who had captured it kept access, the
user had no way to take it back, and changing your password did not end the
session someone else was using.

The end-to-end tests are the ones that matter here. A unit test of the
denylist proves the data structure works; only driving the real endpoints
proves that logging out actually stops the next request.
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core import token_revocation
from app.core.security import create_access_token, decode_token
from app.core.token_revocation import (
    is_revoked,
    revoke_token,
    revoke_all_for_user,
    _mem_revoked_tokens,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_revocation_state():
    token_revocation._reset_for_tests()
    yield
    token_revocation._reset_for_tests()


def _new_account(prefix: str):
    email = f"{prefix}@example.com"
    password = "RevokeTest123!"
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Revoke Test", "company": "Co"},
    )
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"], email, password


class TestTokenClaims:
    def test_tokens_carry_jti_and_iat(self):
        """Without both, revocation is impossible: `jti` identifies one token,
        `iat` lets a per-user cutoff revoke all of them at once."""
        payload = decode_token(create_access_token({"sub": "u1", "email": "a@b.com"}))
        assert payload.get("jti")
        assert payload.get("iat")

    def test_each_token_gets_a_distinct_jti(self):
        """Shared jtis would make revoking one revoke somebody else's."""
        a = decode_token(create_access_token({"sub": "u1"}))["jti"]
        b = decode_token(create_access_token({"sub": "u1"}))["jti"]
        assert a != b


class TestDenylist:
    def test_a_revoked_jti_reads_as_revoked(self):
        revoke_token(None, "jti-1", time.time() + 60)
        assert is_revoked(None, "jti-1", None, None) is True

    def test_an_unrelated_token_is_unaffected(self):
        revoke_token(None, "jti-1", time.time() + 60)
        assert is_revoked(None, "jti-2", None, None) is False

    def test_an_entry_stops_applying_once_the_token_would_have_expired(self):
        """The denylist must not grow forever: an entry is worthless once the
        token it names could no longer have been used anyway."""
        revoke_token(None, "jti-old", time.time() - 1)
        assert is_revoked(None, "jti-old", None, None) is False

    def test_user_cutoff_revokes_every_token_issued_before_it(self):
        issued_before = time.time() - 5
        revoke_all_for_user(None, "user-1", ttl_seconds=3600)
        assert is_revoked(None, "some-jti", "user-1", issued_before) is True

    def test_user_cutoff_does_not_revoke_a_token_issued_afterwards(self):
        """Logging back in after a password reset has to work."""
        revoke_all_for_user(None, "user-1", ttl_seconds=3600)
        issued_after = time.time() + 5
        assert is_revoked(None, "fresh-jti", "user-1", issued_after) is False

    def test_one_users_cutoff_does_not_affect_another(self):
        revoke_all_for_user(None, "user-1", ttl_seconds=3600)
        assert is_revoked(None, "jti", "user-2", time.time() - 5) is False

    def test_memory_store_is_bounded(self):
        """A per-logout entry that is never dropped is its own outage."""
        now = time.time()
        for i in range(token_revocation._MAX_MEM_ENTRIES + 1500):
            _mem_revoked_tokens[f"jti-{i}"] = now + 3600
        revoke_token(None, "one-more", now + 3600)
        assert len(_mem_revoked_tokens) <= token_revocation._MAX_MEM_ENTRIES + 1500


class TestDegradesWhenRedisIsDown:
    """Availability of the auth path is itself a security property.

    An earlier version of this rejected the request when the store could not
    be read. With Redis unreachable that returned 401 for EVERY authenticated
    request — a Redis blip on free-tier infrastructure becomes a total
    outage. The check degrades to the local denylist instead.
    """

    class BrokenRedis:
        def get(self, *_a, **_k):
            raise ConnectionError("redis is down")

        def setex(self, *_a, **_k):
            raise ConnectionError("redis is down")

    def test_a_read_failure_does_not_raise(self):
        assert is_revoked(self.BrokenRedis(), "jti-x", "user-x", time.time()) is False

    def test_a_read_failure_still_honours_locally_known_revocations(self):
        revoke_token(None, "jti-local", time.time() + 60)
        assert is_revoked(self.BrokenRedis(), "jti-local", None, None) is True

    def test_a_write_failure_falls_back_to_memory_instead_of_doing_nothing(self):
        """A logout that silently fails to revoke is the original bug."""
        broken = self.BrokenRedis()
        revoke_token(broken, "jti-y", time.time() + 60)
        assert is_revoked(None, "jti-y", None, None) is True


class TestEndToEnd:
    def test_a_token_stops_working_after_logout(self):
        """The headline fix."""
        token, _, _ = _new_account("revoke_logout")
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/api/v1/reports", headers=headers).status_code == 200

        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200

        after = client.get("/api/v1/reports", headers=headers)
        assert after.status_code == 401, (
            "the token still worked after logout — signing out must actually "
            "end the session, not just clear the cookie"
        )

    def test_logout_does_not_affect_a_different_users_session(self):
        token_a, _, _ = _new_account("revoke_user_a")
        token_b, _, _ = _new_account("revoke_user_b")

        client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token_a}"})

        assert client.get(
            "/api/v1/reports", headers={"Authorization": f"Bearer {token_b}"}
        ).status_code == 200

    def test_logout_on_one_device_leaves_another_device_signed_in(self):
        """"Sign out" here should not sign you out on your phone.

        Two devices means two cookie jars, so this uses two independent
        clients. Two logins through ONE client is a different situation — the
        second overwrites the first's session cookie, and both tokens belong
        to that one browser, so ending that browser's session ends both. That
        distinction is the whole reason logout revokes a same-user cookie
        alongside the header token.
        """
        _, email, password = _new_account("revoke_two_devices")

        laptop = TestClient(app)
        phone = TestClient(app)
        laptop_token = laptop.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        ).json()["access_token"]
        phone_token = phone.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        ).json()["access_token"]
        assert laptop_token != phone_token

        laptop.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {laptop_token}"})

        assert laptop.get(
            "/api/v1/reports", headers={"Authorization": f"Bearer {laptop_token}"}
        ).status_code == 401
        assert phone.get(
            "/api/v1/reports", headers={"Authorization": f"Bearer {phone_token}"}
        ).status_code == 200

    def test_a_cookie_alone_cannot_terminate_a_session(self):
        """The cross-site forced-logout case.

        The session cookie is SameSite=None in the cross-site deployment, so
        a browser attaches it to a request from any site. If the cookie alone
        could revoke, a random page could POST to logout and kill a
        recruiter's active session mid-review. It cannot set an Authorization
        header, so requiring one keeps the destructive half out of reach —
        clearing the cookie is all such a request achieves, exactly as before
        revocation existed.
        """
        from app.core.session_cookies import SESSION_COOKIE_NAME

        token, _, _ = _new_account("revoke_cookie_only")

        attacker_view = TestClient(app)
        attacker_view.cookies.set(SESSION_COOKIE_NAME, token)
        assert attacker_view.post("/api/v1/auth/logout").status_code == 200

        # The victim's token is untouched.
        assert client.get(
            "/api/v1/reports", headers={"Authorization": f"Bearer {token}"}
        ).status_code == 200

    def test_the_session_endpoint_also_rejects_a_revoked_token(self):
        """Logout clears the cookie from the browser, but a cookie value
        captured beforehand must not be able to restore the session."""
        from app.core.session_cookies import SESSION_COOKIE_NAME

        token, _, _ = _new_account("revoke_session_restore")

        restore = TestClient(app)
        restore.cookies.set(SESSION_COOKIE_NAME, token)
        assert restore.get("/api/v1/auth/session").status_code == 200

        client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert restore.get("/api/v1/auth/session").status_code == 401

    def test_logout_succeeds_without_a_token(self):
        """Logout must never fail — a client that cannot complete it leaves
        the user believing they are signed out when they are not."""
        assert client.post("/api/v1/auth/logout").status_code == 200

    def test_logout_succeeds_with_a_garbage_token(self):
        assert client.post(
            "/api/v1/auth/logout", headers={"Authorization": "Bearer not-a-real-token"}
        ).status_code == 200

    def test_logging_in_again_after_logout_works(self):
        """Revocation must not lock the account out."""
        token, email, password = _new_account("revoke_relogin")
        client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})

        fresh = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert fresh.status_code == 200
        assert client.get(
            "/api/v1/reports", headers={"Authorization": f"Bearer {fresh.json()['access_token']}"}
        ).status_code == 200


class TestRevokeAllSessions:
    """The password-reset path.

    Changing your password has to end the sessions that existed before it —
    that is the entire point of resetting a password you believe someone else
    has. If their token keeps working, the reset accomplished nothing.

    These call revoke_all_sessions() directly because the endpoint around it
    requires a live Supabase. That indirection is exactly how a NameError on
    `settings` sat in this function undetected until a linter found it: the
    only code path that reaches it needs infrastructure the test suite does
    not have.
    """

    def test_revoking_all_sessions_is_importable_and_runs(self):
        """Guards the class of bug a missing import causes: this function is
        unreachable in tests via HTTP, so nothing else executes it."""
        from app.api.v1.endpoints.auth import revoke_all_sessions

        revoke_all_sessions(None, "user-reset-1")

    def test_tokens_issued_before_a_reset_stop_working(self):
        from app.api.v1.endpoints.auth import revoke_all_sessions

        issued_before = time.time() - 2
        revoke_all_sessions(None, "user-reset-2")

        assert is_revoked(None, "any-jti", "user-reset-2", issued_before) is True

    def test_a_token_issued_after_the_reset_still_works(self):
        """Logging in with the new password must not be blocked."""
        from app.api.v1.endpoints.auth import revoke_all_sessions

        revoke_all_sessions(None, "user-reset-3")

        assert is_revoked(None, "new-jti", "user-reset-3", time.time() + 2) is False

    def test_other_users_are_unaffected(self):
        from app.api.v1.endpoints.auth import revoke_all_sessions

        revoke_all_sessions(None, "user-reset-4")

        assert is_revoked(None, "jti", "someone-else", time.time() - 2) is False
