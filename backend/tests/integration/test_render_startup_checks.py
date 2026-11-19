"""
Startup checks for the conditions that look healthy on Render and are not:
a database missing a migration, and SMTP on a plan that blocks its ports.
"""

import asyncio
import logging

import pytest

from tests.unit.test_schema_check import SchemaDB


@pytest.fixture
def production(monkeypatch):
    from app.core.config import settings
    from app.core import schema_check

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 48)
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    schema_check.clear_cache()
    yield settings
    schema_check.clear_cache()


def _boot(wait_for=None, timeout=3.0):
    """Run the app's startup and shutdown, optionally waiting for a log line."""
    from app.main import app, lifespan

    async def run():
        async with lifespan(app):
            if wait_for:
                deadline = asyncio.get_running_loop().time() + timeout
                while not wait_for() and asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(0.02)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


class TestSchemaCheckAtStartup:
    def test_a_missing_migration_is_critical_and_names_the_file(self, production, monkeypatch, caplog):
        from app.core import dependencies

        monkeypatch.setattr(production, "SUPABASE_URL", "https://p.supabase.co")
        monkeypatch.setattr(production, "SUPABASE_SERVICE_KEY", "service-key")
        monkeypatch.setattr(dependencies, "get_db", lambda: SchemaDB(missing_tables={"usage_events"}))

        def logged():
            return any("MISSING MIGRATIONS" in r.getMessage() for r in caplog.records)

        with caplog.at_level(logging.CRITICAL, logger="hirelens"):
            _boot(wait_for=logged)
        assert logged(), "a missing migration must be CRITICAL at startup"
        message = next(r.getMessage() for r in caplog.records if "MISSING MIGRATIONS" in r.getMessage())
        assert "007_billing_and_usage.sql" in message
        assert "plan limits are NOT enforced" in message

    def test_a_complete_schema_says_so(self, production, monkeypatch, caplog):
        from app.core import dependencies

        monkeypatch.setattr(production, "SUPABASE_URL", "https://p.supabase.co")
        monkeypatch.setattr(production, "SUPABASE_SERVICE_KEY", "service-key")
        monkeypatch.setattr(dependencies, "get_db", lambda: SchemaDB())

        def logged():
            return any("every migration this code needs is present" in r.getMessage() for r in caplog.records)

        with caplog.at_level(logging.INFO, logger="hirelens"):
            _boot(wait_for=logged)
        assert logged()
        assert not [r for r in caplog.records if "MISSING MIGRATIONS" in r.getMessage()]

    def test_no_supabase_means_no_check(self, production, monkeypatch, caplog):
        from app.core import dependencies

        called = []
        monkeypatch.setattr(dependencies, "get_db", lambda: called.append(1))
        _boot()
        assert called == []


class TestSmtpOnRender:
    def _warned(self, caplog):
        return [r for r in caplog.records if "block ports 25, 465 and 587" in r.getMessage()]

    def test_smtp_on_render_without_resend_warns(self, production, monkeypatch, caplog):
        monkeypatch.setenv("RENDER", "true")
        monkeypatch.setattr(production, "SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setattr(production, "SMTP_PORT", 587)
        with caplog.at_level(logging.WARNING, logger="hirelens"):
            _boot()
        assert self._warned(caplog)

    def test_resend_configured_is_quiet(self, production, monkeypatch, caplog):
        monkeypatch.setenv("RENDER", "true")
        monkeypatch.setattr(production, "SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setattr(production, "RESEND_API_KEY", "re_key")
        monkeypatch.setattr(production, "SMTP_FROM_EMAIL", "HireLens <hi@example.com>")
        with caplog.at_level(logging.WARNING, logger="hirelens"):
            _boot()
        assert not self._warned(caplog)

    def test_not_on_render_is_quiet(self, production, monkeypatch, caplog):
        monkeypatch.delenv("RENDER", raising=False)
        monkeypatch.setattr(production, "SMTP_HOST", "smtp.gmail.com")
        with caplog.at_level(logging.WARNING, logger="hirelens"):
            _boot()
        assert not self._warned(caplog)
