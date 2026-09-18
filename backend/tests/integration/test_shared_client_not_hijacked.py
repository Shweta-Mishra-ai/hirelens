"""
Signing in must not take the service-role key away from the shared client.

supabase-py registers an auth-state listener on every client it creates. On
SIGNED_IN it overwrites that client's own Authorization header with the
*user's* access token and drops its cached PostgREST client:

    supabase/_sync/client.py::_listen_to_auth_events

`auth._headers` is the very same dict object passed to `auth.admin`, so the
admin API loses service-role at the same moment.

When sign-in ran on the process-wide shared client, one person signing in
handed the entire backend to that person: every query afterwards ran under
their RLS policies, `admin.list_users` and `admin.update_user_by_id` stopped
being privileged, and the next user's request was served with the previous
user's token. An hour later their JWT expired and every database call in the
app began failing — for everyone — until someone signed in again.

These tests pin the property that matters: after a login and after a signup,
the shared client still holds the service-role key.
"""

import datetime
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core import dependencies
from app.core.config import settings
from app.main import app


SERVICE_KEY = "service-role-key-for-this-test"
USER_JWT = "user-access-token-that-must-not-leak-onto-the-shared-client"


def _session_for(email: str):
    """The object supabase-py hands its listener on a successful sign-in."""
    from supabase_auth.types import Session, User

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        app_metadata={},
        user_metadata={"full_name": "Test Person", "company": "Acme"},
        aud="authenticated",
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    return Session(
        access_token=USER_JWT,
        token_type="bearer",
        expires_in=3600,
        refresh_token="refresh-token",
        user=user,
    )


def _install_hijacking_auth(client) -> None:
    """
    Replace only the network call, keeping the library's real reaction to a
    successful sign-in: `_notify_all_subscribers("SIGNED_IN", session)`, which
    is the listener that rewrites the client's credentials. Stubbing that out
    would make these tests pass against the very bug they describe.
    """

    def _succeed(credentials):
        session = _session_for(credentials["email"])
        client.auth._notify_all_subscribers("SIGNED_IN", session)
        return _FakeAuthResponse(session)

    client.auth.sign_in_with_password = _succeed
    client.auth.sign_up = _succeed



@pytest.fixture
def supabase_configured(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", SERVICE_KEY)
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon-key")
    dependencies.reset_clients()
    yield
    dependencies.reset_clients()


@pytest.fixture
def shared_client(supabase_configured, monkeypatch):
    """
    A real supabase-py client, with its network layer replaced but its
    auth-state listener left exactly as the library wires it. The listener is
    the thing under test, so stubbing it out would test nothing.
    """
    from supabase import create_client

    client = create_client("https://project.supabase.co", SERVICE_KEY)

    # Deliberately made to SUCCEED rather than refuse. If the endpoint calls
    # the shared client, the call works and the hijack fires on this object —
    # which is precisely the failure these tests exist to catch. Refusing here
    # would prove only that some call happened, not that the shared client
    # kept its key.
    _install_hijacking_auth(client)

    monkeypatch.setattr(dependencies, "_supabase_client", client)
    monkeypatch.setattr(dependencies, "get_db", lambda: client)
    app.dependency_overrides[dependencies.get_db] = lambda: client
    yield client
    app.dependency_overrides.pop(dependencies.get_db, None)


class _FakeAuthResponse:
    def __init__(self, session):
        self.session = session
        self.user = session.user


@pytest.fixture
def throwaway_clients(monkeypatch):
    """
    Capture every single-use auth client the endpoints build, and make its
    sign-in succeed through the library's real notification path so the
    hijack actually fires — on the throwaway, which is the whole point.
    """
    built = []
    real_make = dependencies.make_auth_client

    def fake_make():
        client = real_make()
        assert client is not None, "expected a throwaway client to be built"
        _install_hijacking_auth(client)
        built.append(client)
        return client

    monkeypatch.setattr(dependencies, "make_auth_client", fake_make)
    return built


def _service_role_intact(client) -> bool:
    expected = f"Bearer {SERVICE_KEY}"
    return (
        client.options.headers.get("Authorization") == expected
        and client.auth._headers.get("Authorization") == expected
    )


class TestSharedClientKeepsServiceRole:
    def test_login_does_not_rewrite_the_shared_clients_credentials(
        self, shared_client, throwaway_clients, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.v1.endpoints.auth.accept_pending_invites_for_email",
            lambda *a, **k: 0,
        )
        assert _service_role_intact(shared_client)

        with TestClient(app) as client:
            res = client.post(
                "/api/v1/auth/login",
                json={"email": "person@example.com", "password": "correct-horse"},
            )

        assert res.status_code == 200, res.text
        assert res.json()["access_token"]
        # The assertion that matters, checked first so a regression reports
        # the actual problem rather than a missing helper.
        assert _service_role_intact(shared_client), (
            "the shared client lost service-role to a user's token: every "
            "query in the process now runs as that user"
        )
        assert len(throwaway_clients) == 1, "login must use a single-use client"
        # The hijack still happened — to the throwaway, exactly as intended.
        assert (
            throwaway_clients[0].options.headers.get("Authorization")
            == f"Bearer {USER_JWT}"
        )

    def test_signup_does_not_rewrite_the_shared_clients_credentials(
        self, shared_client, throwaway_clients, monkeypatch
    ):
        monkeypatch.setattr(
            "app.api.v1.endpoints.auth.accept_pending_invites_for_email",
            lambda *a, **k: 0,
        )
        monkeypatch.setattr(
            "app.api.v1.endpoints.auth._count_supabase_users", lambda db: 0, raising=False
        )

        with TestClient(app) as client:
            res = client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "newperson@example.com",
                    "password": "correct-horse-battery",
                    "full_name": "New Person",
                    "company": "Acme",
                },
            )

        assert res.status_code == 200, res.text
        assert _service_role_intact(shared_client), (
            "the shared client lost service-role to a user's token during signup"
        )

    def test_admin_api_keeps_service_role_after_a_login(
        self, shared_client, throwaway_clients, monkeypatch
    ):
        """
        `auth.admin` is handed the same headers dict the listener mutates, so
        a hijack also silently de-privileges admin.update_user_by_id — the
        call every password reset depends on.
        """
        monkeypatch.setattr(
            "app.api.v1.endpoints.auth.accept_pending_invites_for_email",
            lambda *a, **k: 0,
        )
        assert shared_client.auth.admin._headers is shared_client.auth._headers

        with TestClient(app) as client:
            client.post(
                "/api/v1/auth/login",
                json={"email": "person@example.com", "password": "correct-horse"},
            )

        assert (
            shared_client.auth.admin._headers.get("Authorization")
            == f"Bearer {SERVICE_KEY}"
        ), "password reset and team invites just lost their privileges"


class TestThrowawayClientIsDisposable:
    def test_it_does_not_start_a_background_refresh_timer(self, supabase_configured):
        """
        A refresh timer on a client that is about to be dropped is a thread
        holding a session nothing will ever use again.
        """
        client = dependencies.make_auth_client()
        assert client is not None
        try:
            assert client.auth._auto_refresh_token is False
            assert client.auth._persist_session is False
        finally:
            dependencies.close_auth_client(client)

    def test_each_call_gets_its_own_client(self, supabase_configured):
        a = dependencies.make_auth_client()
        b = dependencies.make_auth_client()
        try:
            assert a is not None and b is not None
            assert a is not b, "a shared client would carry the hijack across users"
        finally:
            dependencies.close_auth_client(a)
            dependencies.close_auth_client(b)

    def test_context_manager_closes_even_when_the_body_raises(
        self, supabase_configured, monkeypatch
    ):
        """Every wrong password raises out of that `with` block."""
        closed = []
        monkeypatch.setattr(
            dependencies, "close_auth_client", lambda c: closed.append(c)
        )
        with pytest.raises(ValueError):
            with dependencies.auth_client() as sb:
                assert sb is not None
                raise ValueError("bad password")
        assert len(closed) == 1

    def test_returns_none_when_supabase_is_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "SUPABASE_URL", "")
        monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "")
        assert dependencies.make_auth_client() is None


class TestServiceRoleGuard:
    """
    The endpoints no longer authenticate on the shared client. This is the
    second line of defence, for code written later by someone who does not
    know the rule.
    """

    @pytest.fixture
    def guarded(self, supabase_configured):
        dependencies.reset_clients()
        client = dependencies.get_db()
        assert client is not None
        return client

    def test_a_sign_in_on_the_shared_client_is_undone_and_logged(
        self, guarded, caplog
    ):
        expected = f"Bearer {SERVICE_KEY}"
        assert guarded.options.headers.get("Authorization") == expected

        with caplog.at_level("CRITICAL"):
            guarded.auth._notify_all_subscribers(
                "SIGNED_IN", _session_for("someone@example.com")
            )

        assert guarded.options.headers.get("Authorization") == expected
        assert guarded.auth._headers.get("Authorization") == expected
        assert guarded.postgrest.session.headers.get("Authorization") == expected
        assert any(
            "SHARED Supabase client" in r.message for r in caplog.records
        ), "a silent recovery is barely better than the bug"

    def test_the_admin_api_is_restored_too(self, guarded):
        guarded.auth._notify_all_subscribers(
            "SIGNED_IN", _session_for("someone@example.com")
        )
        assert (
            guarded.auth.admin._headers.get("Authorization")
            == f"Bearer {SERVICE_KEY}"
        )

    def test_it_stays_quiet_when_nothing_changed(self, guarded, caplog):
        with caplog.at_level("CRITICAL"):
            guarded.auth._notify_all_subscribers("SIGNED_OUT", None)
        assert not [r for r in caplog.records if "SHARED" in r.message]
