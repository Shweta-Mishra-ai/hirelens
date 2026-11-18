"""
HireLens — LLM Provider Fallback Tests
Run: cd backend && python -m pytest tests/unit/test_llm_fallback.py -v

These prove the Gemini → Groq → Anthropic fallback chain in engine.llm_call
actually falls through correctly when a provider fails — using mocked
provider calls so no real API keys are needed. This directly targets the
reported bug: Groq's model name (llama-3.1-70b-versatile) had been fully
deprecated since Jan 2025, so whenever Gemini's free tier rate-limited,
the "fallback" was silently failing too. That's now fixed to
openai/gpt-oss-120b; these tests guard against it breaking again.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from app.core.exceptions import LLMError


def _set_keys(monkeypatch, gemini=None, groq=None, anthropic=None):
    from app.core.config import settings
    monkeypatch.setattr(settings, "GEMINI_API_KEY", gemini or "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", groq or "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", anthropic or "")


class TestProviderFallbackChain:
    @pytest.mark.asyncio
    async def test_no_keys_configured_raises_clear_error(self, monkeypatch):
        from app.services.ai import engine
        _set_keys(monkeypatch)  # all empty

        with pytest.raises(LLMError, match="No LLM API key configured"):
            await engine.llm_call("test prompt")

    @pytest.mark.asyncio
    async def test_falls_through_to_groq_when_gemini_fails(self, monkeypatch):
        from app.services.ai import engine
        _set_keys(monkeypatch, gemini="fake-gemini-key", groq="fake-groq-key")

        async def failing_gemini(prompt, **kw):
            raise LLMError("Gemini rate limit exceeded")

        async def working_groq(prompt, **kw):
            return '{"result": "from-groq"}'

        monkeypatch.setattr(engine, "_call_gemini", failing_gemini)
        monkeypatch.setattr(engine, "_call_groq", working_groq)

        result = await engine.llm_call("test prompt")
        assert result == {"result": "from-groq"}

    @pytest.mark.asyncio
    async def test_falls_through_to_anthropic_when_gemini_and_groq_fail(self, monkeypatch):
        from app.services.ai import engine
        _set_keys(monkeypatch, gemini="k1", groq="k2", anthropic="k3")

        async def failing(prompt, **kw):
            raise LLMError("provider down")

        async def working_anthropic(prompt, **kw):
            return '{"result": "from-anthropic"}'

        monkeypatch.setattr(engine, "_call_gemini", failing)
        monkeypatch.setattr(engine, "_call_groq", failing)
        monkeypatch.setattr(engine, "_call_anthropic", working_anthropic)

        result = await engine.llm_call("test prompt")
        assert result == {"result": "from-anthropic"}

    @pytest.mark.asyncio
    async def test_rate_limit_skips_remaining_retries_and_moves_to_next_provider(self, monkeypatch):
        from app.services.ai import engine
        _set_keys(monkeypatch, gemini="k1", groq="k2")

        call_count = {"gemini": 0}

        async def rate_limited_gemini(prompt, **kw):
            call_count["gemini"] += 1
            raise LLMError("Gemini rate limit exceeded — 429")

        async def working_groq(prompt, **kw):
            return '{"result": "ok"}'

        monkeypatch.setattr(engine, "_call_gemini", rate_limited_gemini)
        monkeypatch.setattr(engine, "_call_groq", working_groq)

        result = await engine.llm_call("test prompt")
        assert result == {"result": "ok"}
        # A rate limit breaks out after the FIRST attempt on each Gemini model
        # rather than retrying it.
        assert call_count["gemini"] == len(engine.gemini_models())

    @pytest.mark.asyncio
    async def test_all_providers_failing_raises_llm_error(self, monkeypatch):
        from app.services.ai import engine
        _set_keys(monkeypatch, gemini="k1", groq="k2")

        async def always_fails(prompt, **kw):
            raise LLMError("down")

        monkeypatch.setattr(engine, "_call_gemini", always_fails)
        monkeypatch.setattr(engine, "_call_groq", always_fails)

        with pytest.raises(LLMError):
            await engine.llm_call("test prompt")

    @pytest.mark.asyncio
    async def test_malformed_json_from_one_provider_falls_through(self, monkeypatch):
        from app.services.ai import engine
        _set_keys(monkeypatch, gemini="k1", groq="k2")

        async def bad_json_gemini(prompt, **kw):
            return "this is not json at all, sorry"

        async def working_groq(prompt, **kw):
            return '{"ok": true}'

        monkeypatch.setattr(engine, "_call_gemini", bad_json_gemini)
        monkeypatch.setattr(engine, "_call_groq", working_groq)

        result = await engine.llm_call("test prompt")
        assert result == {"ok": True}


class TestProviderModelNamesAreCurrent:
    """Regression guard: catches the exact class of bug that was reported
    (a provider's hardcoded model string silently becoming invalid/deprecated)."""

    def test_groq_model_is_not_the_known_deprecated_one(self):
        from app.core.config import settings
        assert settings.GROQ_MODEL != "llama-3.1-70b-versatile", (
            "llama-3.1-70b-versatile was deprecated by Groq in Jan 2025 — "
            "using it makes the Groq fallback silently fail on every call."
        )

    def test_anthropic_model_is_not_a_retired_one(self):
        from app.core.config import settings
        assert settings.ANTHROPIC_MODEL
        assert not settings.ANTHROPIC_MODEL.startswith("claude-3"), (
            "Claude 3.x models are retired; the Anthropic fallback would 404 on every call."
        )

    def test_model_names_are_configuration_not_code(self):
        import inspect
        from app.services.ai import engine
        for fn in (engine._call_gemini, engine._call_groq, engine._call_anthropic):
            source = inspect.getsource(fn)
            assert "gemini-2.5-flash" not in source
            assert "llama-3.3-70b-versatile" not in source
            assert "claude-sonnet" not in source



class TestProviderOrder:
    @pytest.mark.asyncio
    async def test_groq_can_be_put_first(self, monkeypatch):
        from app.core.config import settings
        from app.services.ai import engine
        _set_keys(monkeypatch, gemini="k1", groq="k2")
        monkeypatch.setattr(settings, "LLM_PROVIDER_ORDER", "groq,gemini")
        called = []

        async def gemini(prompt, **kw):
            called.append("gemini")
            return '{"via": "gemini"}'

        async def groq(prompt, **kw):
            called.append("groq")
            return '{"via": "groq"}'

        monkeypatch.setattr(engine, "_call_gemini", gemini)
        monkeypatch.setattr(engine, "_call_groq", groq)
        assert await engine.llm_call("p") == {"via": "groq"}
        assert called == ["groq"]

    @pytest.mark.asyncio
    async def test_a_provider_missing_from_the_order_still_runs_last(self, monkeypatch):
        from app.core.config import settings
        from app.services.ai import engine
        _set_keys(monkeypatch, gemini="k1", groq="k2")
        monkeypatch.setattr(settings, "LLM_PROVIDER_ORDER", "groq")

        async def failing_groq(prompt, **kw):
            raise LLMError("Groq rate limit hit.")

        async def gemini(prompt, **kw):
            return '{"via": "gemini"}'

        monkeypatch.setattr(engine, "_call_groq", failing_groq)
        monkeypatch.setattr(engine, "_call_gemini", gemini)
        assert await engine.llm_call("p") == {"via": "gemini"}
