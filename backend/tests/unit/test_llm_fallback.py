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


async def _fast_sleep(*_a, **_k):
    """llm_call() sleeps 2s between retry attempts on a real failure — fine
    for a couple of tests, but the 4-provider chain tests below deliberately
    fail every provider, which would otherwise cost several real seconds."""
    return None


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
        # Rate-limit should break out after the FIRST attempt, not retry twice
        assert call_count["gemini"] == 1

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
        import inspect
        from app.services.ai import engine
        source = inspect.getsource(engine._call_groq)
        assert "llama-3.1-70b-versatile" not in source, (
            "llama-3.1-70b-versatile was deprecated by Groq in Jan 2025 — "
            "using it makes the Groq fallback silently fail on every call."
        )

    def test_anthropic_model_string_is_set(self):
        import inspect
        from app.services.ai import engine
        source = inspect.getsource(engine._call_anthropic)
        assert '"model":' in source

    def test_llm_call_wires_up_two_distinct_groq_models(self):
        """Two Groq-hosted providers, same GROQ_API_KEY, different `model=`."""
        import inspect
        from app.services.ai import engine
        source = inspect.getsource(engine.llm_call)
        assert "llama-3.3-70b-versatile" in source
        assert "openai/gpt-oss-120b" in source


class TestFourProviderChain:
    """Gemini -> Groq(Llama) -> Anthropic -> Groq(gpt-oss-120b).

    gpt-oss-120b is deliberately placed AFTER Anthropic, not instead of it:
    anyone with an Anthropic key keeps it; anyone without one still gets a
    working last-resort option built on the GROQ_API_KEY they already need
    for the second provider — no new key required.
    """

    @pytest.mark.asyncio
    async def test_groq_only_configured_yields_two_distinct_groq_attempts(self, monkeypatch):
        from app.services.ai import engine
        _set_keys(monkeypatch, groq="only-groq-key")
        monkeypatch.setattr(engine.asyncio, "sleep", _fast_sleep)

        seen_models = []

        async def capturing_groq(prompt, model="llama-3.3-70b-versatile", **kw):
            seen_models.append(model)
            raise LLMError("down")

        monkeypatch.setattr(engine, "_call_groq", capturing_groq)

        with pytest.raises(LLMError):
            await engine.llm_call("test prompt")

        # 2 attempts per provider, and both Groq-hosted models get tried
        assert seen_models.count("llama-3.3-70b-versatile") == 2
        assert seen_models.count("openai/gpt-oss-120b") == 2

    @pytest.mark.asyncio
    async def test_anthropic_is_kept_and_gpt_oss_120b_is_the_true_last_resort(self, monkeypatch):
        from app.services.ai import engine
        _set_keys(monkeypatch, gemini="k1", groq="k2", anthropic="k3")
        monkeypatch.setattr(engine.asyncio, "sleep", _fast_sleep)

        order = []

        async def fail_gemini(prompt, **kw):
            order.append("gemini")
            raise LLMError("down")

        async def fail_groq(prompt, model="llama-3.3-70b-versatile", **kw):
            order.append(f"groq:{model}")
            raise LLMError("down")

        async def fail_anthropic(prompt, **kw):
            order.append("anthropic")
            raise LLMError("down")

        monkeypatch.setattr(engine, "_call_gemini", fail_gemini)
        monkeypatch.setattr(engine, "_call_groq", fail_groq)
        monkeypatch.setattr(engine, "_call_anthropic", fail_anthropic)

        with pytest.raises(LLMError):
            await engine.llm_call("test prompt")

        # Reduce to the sequence of distinct provider "rounds" as they first appear.
        seen_bases = [e.split(":")[0] for e in order]
        first_of_each = []
        for b in seen_bases:
            if b not in first_of_each:
                first_of_each.append(b)
        assert first_of_each == ["gemini", "groq", "anthropic"], (
            "groq's SECOND registration (gpt-oss-120b) only shows up as a new "
            "base name 'groq' again, not a new entry in first_of_each, but it "
            "must still run after anthropic — checked below via the raw order."
        )
        assert order[-1] == "groq:openai/gpt-oss-120b", (
            "gpt-oss-120b must be the very last thing attempted, after Anthropic"
        )
        assert "groq:llama-3.3-70b-versatile" in order
        assert "anthropic" in order
        # anthropic must run before the gpt-oss-120b attempts
        assert order.index("anthropic") < order.index("groq:openai/gpt-oss-120b")

    @pytest.mark.asyncio
    async def test_gpt_oss_120b_answers_when_it_is_the_only_survivor(self, monkeypatch):
        """The whole point of this fallback: no Anthropic key, Gemini and the
        primary Groq model both down -> the app still returns a real answer."""
        from app.services.ai import engine
        _set_keys(monkeypatch, gemini="k1", groq="k2")  # no anthropic configured
        monkeypatch.setattr(engine.asyncio, "sleep", _fast_sleep)

        async def fail_gemini(prompt, **kw):
            raise LLMError("down")

        async def groq_dispatch(prompt, model="llama-3.3-70b-versatile", **kw):
            if model == "openai/gpt-oss-120b":
                return '{"result": "from-gpt-oss-120b"}'
            raise LLMError("llama model down too")

        monkeypatch.setattr(engine, "_call_gemini", fail_gemini)
        monkeypatch.setattr(engine, "_call_groq", groq_dispatch)

        result = await engine.llm_call("test prompt")
        assert result == {"result": "from-gpt-oss-120b"}
