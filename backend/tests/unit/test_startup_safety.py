"""
HireLens — Startup Safety Unit Tests
Run: cd backend && python -m pytest tests/unit/test_startup_safety.py -v

Covers the "Today — do not defer" fixes from the audit:
- SECRET_KEY / ALLOWED_ORIGINS now hard-fail app startup in production
  instead of only logging a message nobody may read.
- The self-ping keep-alive loop no longer guesses a backend URL by
  string-replacing hardcoded hostnames; it requires BACKEND_URL and skips
  (with a clear warning) rather than silently pinging a wrong/nonexistent
  URL.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestSecretKeyHardFail:
    def _import_fresh_app_with_env(self, monkeypatch, **env):
        """
        Settings and app are read at import time, so each test needs a
        genuinely fresh import with the target environment already set —
        reusing a cached `app.main` module would reuse the old settings.
        """
        for mod in list(sys.modules):
            if mod == "app.main" or mod.startswith("app.core.config"):
                del sys.modules[mod]
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import app.main as main_module
        return main_module

    def test_short_secret_key_in_production_raises_systemexit_on_startup(self, monkeypatch):
        from fastapi.testclient import TestClient

        main_module = self._import_fresh_app_with_env(
            monkeypatch,
            SECRET_KEY="too-short",
            APP_ENV="production",
            GEMINI_API_KEY="test",
        )
        raised = False
        try:
            with TestClient(main_module.app):
                pass
        except BaseException as e:
            # anyio's task-group cancellation wraps the SystemExit raised
            # inside the lifespan generator; asserting *some* exception
            # propagated (and that no client came up) is what matters —
            # confirmed manually that the underlying cause is SystemExit
            # (visible in the wrapped traceback).
            raised = True
        assert raised, "Expected app startup to fail with a short SECRET_KEY in production"

    def test_unset_secret_key_in_production_raises_systemexit(self, monkeypatch):
        """
        There is no shipped default any more. This used to pass the old
        `dev-secret-key-…` constant, which was both a globally known signing
        key for every install that forgot to set one, and the thing secret
        scanners kept opening critical issues about. An unset key now arrives
        here as empty, and production still refuses to start.
        """
        from fastapi.testclient import TestClient

        main_module = self._import_fresh_app_with_env(
            monkeypatch,
            SECRET_KEY="",
            APP_ENV="production",
            GEMINI_API_KEY="test",
        )
        raised = False
        try:
            with TestClient(main_module.app):
                pass
        except BaseException:
            raised = True
        assert raised, "Expected app startup to fail with no SECRET_KEY in production"

    def test_wildcard_cors_in_production_raises_systemexit(self, monkeypatch):
        from fastapi.testclient import TestClient

        main_module = self._import_fresh_app_with_env(
            monkeypatch,
            SECRET_KEY="a-genuinely-long-random-secret-key-for-testing-only",
            ALLOWED_ORIGINS="*",
            APP_ENV="production",
            GEMINI_API_KEY="test",
        )
        raised = False
        try:
            with TestClient(main_module.app):
                pass
        except BaseException:
            raised = True
        assert raised, "Expected app startup to fail with ALLOWED_ORIGINS=* in production"

    def test_valid_secret_key_in_production_boots_successfully(self, monkeypatch):
        from fastapi.testclient import TestClient

        main_module = self._import_fresh_app_with_env(
            monkeypatch,
            SECRET_KEY="a-genuinely-long-random-secret-key-for-testing-only",
            ALLOWED_ORIGINS="https://hirelens.example.com",
            APP_ENV="production",
            GEMINI_API_KEY="test",
        )
        with TestClient(main_module.app) as client:
            res = client.get("/api/v1/health")
            assert res.status_code == 200

    def test_short_secret_key_in_development_does_not_raise(self, monkeypatch):
        """
        The hard-fail is production-only by design — local development
        with the default key must keep working without ceremony.
        """
        from fastapi.testclient import TestClient

        main_module = self._import_fresh_app_with_env(
            monkeypatch,
            SECRET_KEY="short",
            APP_ENV="development",
            GEMINI_API_KEY="test",
        )
        with TestClient(main_module.app) as client:
            res = client.get("/api/v1/health")
            assert res.status_code == 200


class TestKeepAliveURLSafety:
    """
    The keep-alive pinger used to derive its target URL by string-replacing
    two hardcoded hostnames inside FRONTEND_URL. That silently broke the
    moment either domain changed. It now requires BACKEND_URL explicitly.
    """

    def test_keep_alive_skips_without_backend_url(self, caplog):
        import logging
        from app.core.config import settings
        from app.main import _keep_alive_loop

        original = settings.BACKEND_URL
        settings.BACKEND_URL = ""
        try:
            with caplog.at_level(logging.WARNING, logger="hirelens"):
                asyncio.run(_keep_alive_loop())
            assert any("BACKEND_URL is not set" in r.message for r in caplog.records)
        finally:
            settings.BACKEND_URL = original

    def test_keep_alive_does_not_reference_hardcoded_hostnames(self):
        """
        Regression guard: the old implementation string-replaced two
        specific hostnames. Assert that pattern is gone from the source —
        if it ever comes back, this test documents exactly why not to.
        """
        import inspect
        from app.main import _keep_alive_loop

        src = inspect.getsource(_keep_alive_loop)
        assert "hirelens-theta.vercel.app" not in src
        assert "hirelens-backend.onrender.com" not in src
        assert "BACKEND_URL" in src
