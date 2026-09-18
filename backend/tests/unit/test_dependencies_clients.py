"""
HireLens — Shared client dependencies

These cover the two rules get_redis()/get_db() have to follow when the
dependency behind them is unhealthy, because the failure mode is not a crash:
the app keeps answering, just slowly enough to be unusable.

Run: cd backend && python -m pytest tests/unit/test_dependencies_clients.py -v
"""
import time
import pytest

import app.core.dependencies as deps
from app.core.config import settings


@pytest.fixture(autouse=True)
def clean_clients():
    original_url = settings.REDIS_URL
    original_pw = settings.REDIS_PASSWORD
    deps.reset_clients()
    yield
    deps.reset_clients()
    settings.REDIS_URL = original_url
    settings.REDIS_PASSWORD = original_pw


class FakeRedisModule:
    """Stands in for the `redis` package: from_url returns a client whose
    ping() does whatever the test asked for."""

    def __init__(self, ping_raises=None):
        self.ping_raises = ping_raises
        self.from_url_calls = 0
        self.closed = 0

    def from_url(self, url, **kwargs):
        self.from_url_calls += 1
        module = self

        class Client:
            def ping(self):
                if module.ping_raises:
                    raise module.ping_raises
                return True

            def close(self):
                module.closed += 1

        return Client()


def _install(monkeypatch, module):
    import sys
    monkeypatch.setitem(sys.modules, "redis", module)
    settings.REDIS_URL = "redis://example.invalid:6379/0"


class TestRedisClientIsVerifiedBeforeItIsPublished:
    def test_a_failed_ping_never_leaves_a_client_behind(self, monkeypatch):
        """
        The bug this exists for: the client was assigned to the module global
        *before* ping() ran. The first call returned None correctly, and every
        call after it returned the unverified client from the cache — so a
        single failed health check at startup meant every later request paid
        the full connection timeout before falling back. Measured at 3s per
        request against an address that drops packets.
        """
        module = FakeRedisModule(ping_raises=OSError("Timeout connecting to server"))
        _install(monkeypatch, module)

        assert deps.get_redis() is None
        # Second call must still report unavailable, not hand back the client
        # that just failed its probe.
        assert deps.get_redis() is None
        assert deps._redis_client is None

    def test_the_failed_client_is_closed_not_leaked(self, monkeypatch):
        module = FakeRedisModule(ping_raises=OSError("nope"))
        _install(monkeypatch, module)
        deps.get_redis()
        assert module.closed == 1

    def test_a_healthy_client_is_cached(self, monkeypatch):
        module = FakeRedisModule()
        _install(monkeypatch, module)

        first = deps.get_redis()
        second = deps.get_redis()

        assert first is not None
        assert first is second
        assert module.from_url_calls == 1


class TestFailureCooldown:
    def test_a_failure_is_not_retried_on_every_call(self, monkeypatch):
        """Without the cooldown an unreachable Redis costs one connection
        timeout per request — sign-in, upload, batch polling, all of it."""
        module = FakeRedisModule(ping_raises=OSError("unreachable"))
        _install(monkeypatch, module)

        for _ in range(20):
            assert deps.get_redis() is None

        assert module.from_url_calls == 1

    def test_recovery_is_picked_up_once_the_cooldown_passes(self, monkeypatch):
        module = FakeRedisModule(ping_raises=OSError("unreachable"))
        _install(monkeypatch, module)

        assert deps.get_redis() is None
        assert module.from_url_calls == 1

        # Redis comes back, and the cooldown expires.
        module.ping_raises = None
        deps._redis_failed_at = time.monotonic() - (deps._PROBE_COOLDOWN_SECONDS + 1)

        assert deps.get_redis() is not None
        assert module.from_url_calls == 2

    def test_unconfigured_redis_never_probes(self, monkeypatch):
        module = FakeRedisModule()
        _install(monkeypatch, module)
        settings.REDIS_URL = ""

        assert deps.get_redis() is None
        assert module.from_url_calls == 0


class TestSupabaseClient:
    def test_unconfigured_returns_none(self):
        url, key = settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY
        try:
            settings.SUPABASE_URL = ""
            settings.SUPABASE_SERVICE_KEY = ""
            assert deps.get_db() is None
        finally:
            settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY = url, key

    def test_creation_failure_is_not_retried_on_every_call(self, monkeypatch):
        import sys

        calls = {"n": 0}

        class FakeSupabase:
            @staticmethod
            def create_client(url, key):
                calls["n"] += 1
                raise RuntimeError("bad key")

        monkeypatch.setitem(sys.modules, "supabase", FakeSupabase)
        url, key = settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY
        try:
            settings.SUPABASE_URL = "https://example.supabase.co"
            settings.SUPABASE_SERVICE_KEY = "service-key"
            for _ in range(10):
                assert deps.get_db() is None
            assert calls["n"] == 1
        finally:
            settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY = url, key

    def test_a_working_client_is_cached(self, monkeypatch):
        import sys

        sentinel = object()
        calls = {"n": 0}

        class FakeSupabase:
            @staticmethod
            def create_client(url, key):
                calls["n"] += 1
                return sentinel

        monkeypatch.setitem(sys.modules, "supabase", FakeSupabase)
        url, key = settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY
        try:
            settings.SUPABASE_URL = "https://example.supabase.co"
            settings.SUPABASE_SERVICE_KEY = "service-key"
            assert deps.get_db() is sentinel
            assert deps.get_db() is sentinel
            assert calls["n"] == 1
        finally:
            settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY = url, key
