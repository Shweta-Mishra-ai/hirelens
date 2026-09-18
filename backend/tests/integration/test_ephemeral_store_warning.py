"""
Production on the local SQLite store must never be silent.

Running without Supabase is a legitimate choice for a demo. It is a disaster
quietly: on an ephemeral container filesystem — Render's free plan, or any
redeploy — /app/data/local.db is destroyed along with every account in it, and
people who signed up successfully simply cannot sign in any more. Nothing in
the logs connected the two.
"""

class TestEphemeralStoreWarning:
    """
    Running production on the local SQLite store is allowed, but it must never
    be silent: on an ephemeral container filesystem that file — and every
    account in it — is destroyed on the next deploy or wake from sleep.
    """

    def test_production_without_supabase_says_so_loudly(self, monkeypatch, caplog):
        from app.core.config import settings
        from app.main import lifespan, app
        import asyncio

        monkeypatch.setattr(settings, "APP_ENV", "production")
        monkeypatch.setattr(settings, "SECRET_KEY", "x" * 48)
        monkeypatch.setattr(settings, "ALLOWED_ORIGINS", "https://app.example.com")
        monkeypatch.setattr(settings, "SUPABASE_URL", "")
        monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "")

        async def run():
            async with lifespan(app):
                pass

        with caplog.at_level("CRITICAL"):
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(run())

        assert any(
            "No Supabase configured in production" in r.message
            for r in caplog.records
        ), "the local store on an ephemeral disk must not be a silent default"

    def test_production_with_supabase_stays_quiet(self, monkeypatch, caplog):
        from app.core.config import settings
        from app.main import lifespan, app
        import asyncio

        monkeypatch.setattr(settings, "APP_ENV", "production")
        monkeypatch.setattr(settings, "SECRET_KEY", "x" * 48)
        monkeypatch.setattr(settings, "ALLOWED_ORIGINS", "https://app.example.com")
        monkeypatch.setattr(settings, "SUPABASE_URL", "https://p.supabase.co")
        monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "service-key")

        async def run():
            async with lifespan(app):
                pass

        with caplog.at_level("CRITICAL"):
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(run())

        assert not [
            r for r in caplog.records if "No Supabase configured" in r.message
        ]
