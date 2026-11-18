"""
What the three LLM providers actually send and how their answers are read.

test_llm_fallback.py covers the dispatcher's choice of provider by stubbing
the callers out entirely. That left the callers themselves — the code that
builds each request and unpacks each response shape — with no tests at all,
even though this is the path every single analysis runs through, and the
place a provider-side change (a renamed model, a different envelope, a
safety block) shows up first.

Every request here is served by an httpx MockTransport; nothing leaves the
process.
"""

import httpx
import pytest

from app.core.config import settings
from app.core.exceptions import LLMError
from app.services.ai import engine


@pytest.fixture
def transport(monkeypatch):
    """Serve every outbound request from a handler the test controls."""
    state = {"handler": None, "requests": []}
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        def handler(request):
            state["requests"].append(request)
            return state["handler"](request)

        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gemini-key-abc123")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "groq-key-abc123")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "anthropic-key-abc123")
    return state


def _json_body(request) -> dict:
    import json as _json

    return _json.loads(request.content)


def gemini_body(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class TestGemini:
    @pytest.mark.asyncio
    async def test_a_normal_answer_is_returned(self, transport):
        transport["handler"] = lambda r: httpx.Response(200, json=gemini_body('{"name": "Anita"}'))
        assert await engine._call_gemini("prompt") == '{"name": "Anita"}'

    @pytest.mark.asyncio
    async def test_the_request_carries_the_prompt_and_asks_for_json(self, transport):
        transport["handler"] = lambda r: httpx.Response(200, json=gemini_body("{}"))
        await engine._call_gemini("analyse this resume", temperature=0.3, max_tokens=1234)
        sent = transport["requests"][0]
        import json as _json
        payload = _json.loads(sent.content)
        assert payload["contents"][0]["parts"][0]["text"] == "analyse this resume"
        assert payload["generationConfig"]["temperature"] == 0.3
        # Thinking models get headroom so reasoning cannot crowd out the JSON.
        assert payload["generationConfig"]["maxOutputTokens"] >= 1234
        assert payload["generationConfig"]["responseMimeType"] == "application/json"

    @pytest.mark.asyncio
    async def test_a_gemini_3_model_is_sent_a_thinking_level_not_a_budget(self, transport):
        transport["handler"] = lambda r: httpx.Response(200, json=gemini_body("{}"))
        await engine._call_gemini("p", model="gemini-3.6-flash")
        config = _json_body(transport["requests"][0])["generationConfig"]
        assert config["thinkingConfig"] == {"thinkingLevel": "low"}
        assert "thinkingBudget" not in config["thinkingConfig"]

    @pytest.mark.asyncio
    async def test_a_gemini_2_model_keeps_thinking_off_with_a_zero_budget(self, transport):
        transport["handler"] = lambda r: httpx.Response(200, json=gemini_body("{}"))
        await engine._call_gemini("p", max_tokens=1234, model="gemini-2.5-flash")
        config = _json_body(transport["requests"][0])["generationConfig"]
        assert config["thinkingConfig"] == {"thinkingBudget": 0}
        assert config["maxOutputTokens"] == 1234

    @pytest.mark.asyncio
    async def test_a_rejected_thinking_setting_falls_back_to_the_model_default(self, transport):
        def handler(request):
            config = _json_body(request)["generationConfig"]
            if "thinkingConfig" in config:
                return httpx.Response(400, json={"error": {"message": "Thinking level minimal is not supported"}})
            return httpx.Response(200, json=gemini_body('{"ok": 1}'))

        transport["handler"] = handler
        assert await engine._call_gemini("p", model="gemini-3.8-flash") == '{"ok": 1}'
        assert len(transport["requests"]) == 2

    @pytest.mark.asyncio
    async def test_thought_parts_are_not_mistaken_for_the_answer(self, transport):
        transport["handler"] = lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": "Let me think about the dates...", "thought": True},
            {"text": '{"name": "Anita"}', "thoughtSignature": "abc"},
        ]}}]})
        assert await engine._call_gemini("p") == '{"name": "Anita"}'

    @pytest.mark.asyncio
    async def test_an_overloaded_model_says_so(self, transport):
        transport["handler"] = lambda r: httpx.Response(503)
        with pytest.raises(LLMError, match="overloaded"):
            await engine._call_gemini("p")

    def test_the_default_models_are_current_free_tier_models(self):
        models = engine.gemini_models()
        assert models, "GEMINI_MODEL is empty"
        assert all(not m.startswith("gemini-2") for m in models), (
            "Gemini 2.x models are served only to projects that used them "
            "before September 2026 — a new deployment gets 404 on every call."
        )
        assert len(models) >= 2, "keep a second model to fall back to"

    @pytest.mark.asyncio
    async def test_a_rate_limit_says_so(self, transport):
        transport["handler"] = lambda r: httpx.Response(429)
        with pytest.raises(LLMError, match="rate limit"):
            await engine._call_gemini("prompt")

    @pytest.mark.asyncio
    async def test_a_bad_request_surfaces_the_provider_s_message(self, transport):
        transport["handler"] = lambda r: httpx.Response(
            400, json={"error": {"message": "API key not valid"}}
        )
        with pytest.raises(LLMError, match="API key not valid"):
            await engine._call_gemini("prompt")

    @pytest.mark.asyncio
    async def test_a_server_error_is_an_llm_error(self, transport):
        transport["handler"] = lambda r: httpx.Response(503)
        with pytest.raises(LLMError, match="503"):
            await engine._call_gemini("prompt")

    @pytest.mark.asyncio
    async def test_a_safety_block_is_reported_as_one(self, transport):
        transport["handler"] = lambda r: httpx.Response(
            200, json={"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}
        )
        with pytest.raises(LLMError, match="SAFETY"):
            await engine._call_gemini("prompt")

    @pytest.mark.asyncio
    async def test_an_empty_answer_is_an_error_not_an_empty_report(self, transport):
        transport["handler"] = lambda r: httpx.Response(200, json={"candidates": []})
        with pytest.raises(LLMError, match="no candidates"):
            await engine._call_gemini("prompt")

    @pytest.mark.asyncio
    async def test_empty_content_parts_are_an_error(self, transport):
        transport["handler"] = lambda r: httpx.Response(
            200, json={"candidates": [{"content": {"parts": []}}]}
        )
        with pytest.raises(LLMError, match="empty content parts"):
            await engine._call_gemini("prompt")

    @pytest.mark.asyncio
    async def test_the_key_is_sent_in_a_header_never_in_the_url(self, transport):
        """
        httpx logs every request line, URL included, at INFO. A key in the
        query string therefore reached the platform log on every analysis.
        """
        transport["handler"] = lambda r: httpx.Response(200, json=gemini_body("{}"))
        await engine._call_gemini("prompt")
        sent = transport["requests"][0]
        assert "gemini-key-abc123" not in str(sent.url)
        assert "key=" not in str(sent.url)
        assert sent.headers["x-goog-api-key"] == "gemini-key-abc123"

    @pytest.mark.asyncio
    async def test_the_model_comes_from_configuration(self, transport, monkeypatch):
        monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-test-model")
        transport["handler"] = lambda r: httpx.Response(200, json=gemini_body("{}"))
        await engine._call_gemini("prompt")
        assert "/models/gemini-test-model:generateContent" in str(transport["requests"][0].url)

    @pytest.mark.asyncio
    async def test_a_retired_model_is_named_in_the_error(self, transport):
        transport["handler"] = lambda r: httpx.Response(404)
        with pytest.raises(LLMError, match="GEMINI_MODEL"):
            await engine._call_gemini("prompt")

    @pytest.mark.asyncio
    async def test_a_connection_failure_never_leaks_the_api_key(self, transport):
        def boom(request):
            raise httpx.ConnectError(
                f"failed connecting to {request.url} with {request.headers}", request=request
            )

        transport["handler"] = boom
        with pytest.raises(LLMError) as err:
            await engine._call_gemini("prompt")
        assert "gemini-key-abc123" not in str(err.value)


class TestGroq:
    @pytest.mark.asyncio
    async def test_a_normal_answer_is_returned(self, transport):
        transport["handler"] = lambda r: httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )
        assert await engine._call_groq("prompt") == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_the_request_is_authenticated_and_asks_for_json(self, transport):
        transport["handler"] = lambda r: httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}}]}
        )
        await engine._call_groq("prompt")
        sent = transport["requests"][0]
        import json as _json
        assert sent.headers["Authorization"] == "Bearer groq-key-abc123"
        assert _json.loads(sent.content)["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_a_rate_limit_says_so(self, transport):
        transport["handler"] = lambda r: httpx.Response(429)
        with pytest.raises(LLMError, match="rate limit"):
            await engine._call_groq("prompt")

    @pytest.mark.asyncio
    async def test_an_unexpected_envelope_is_an_error(self, transport):
        transport["handler"] = lambda r: httpx.Response(200, json={"choices": []})
        with pytest.raises(LLMError, match="Unexpected Groq response"):
            await engine._call_groq("prompt")

    @pytest.mark.asyncio
    async def test_a_server_error_is_raised(self, transport):
        transport["handler"] = lambda r: httpx.Response(500)
        with pytest.raises(LLMError, match="overloaded"):
            await engine._call_groq("prompt")

    @pytest.mark.asyncio
    async def test_a_reasoning_model_gets_effort_and_token_headroom(self, transport, monkeypatch):
        monkeypatch.setattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")
        transport["handler"] = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
        await engine._call_groq("prompt", max_tokens=1000)
        body = _json_body(transport["requests"][0])
        assert body["model"] == "openai/gpt-oss-120b"
        assert body["reasoning_effort"] == "low"
        assert body["max_completion_tokens"] > 1000
        assert body["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_a_request_is_kept_inside_the_free_plan_token_limit(self, transport, monkeypatch):
        monkeypatch.setattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")
        monkeypatch.setattr(settings, "GROQ_MAX_REQUEST_TOKENS", 8000)
        transport["handler"] = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
        prompt = "x" * 14_000  # ~4,000 tokens
        await engine._call_groq(prompt, max_tokens=4000)
        body = _json_body(transport["requests"][0])
        assert body["max_completion_tokens"] + len(prompt) / 3.5 <= 8000

    @pytest.mark.asyncio
    async def test_a_prompt_that_cannot_fit_is_refused_before_sending(self, transport, monkeypatch):
        monkeypatch.setattr(settings, "GROQ_MAX_REQUEST_TOKENS", 8000)
        transport["handler"] = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
        with pytest.raises(LLMError, match="too large"):
            await engine._call_groq("x" * 40_000)
        assert transport["requests"] == []

    @pytest.mark.asyncio
    async def test_a_non_reasoning_model_is_not_sent_reasoning_effort(self, transport, monkeypatch):
        monkeypatch.setattr(settings, "GROQ_MODEL", "some-other/chat-model")
        transport["handler"] = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
        await engine._call_groq("prompt", max_tokens=1000)
        body = _json_body(transport["requests"][0])
        assert "reasoning_effort" not in body
        assert body["max_completion_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_a_retired_groq_model_is_named_in_the_error(self, transport):
        transport["handler"] = lambda r: httpx.Response(404, json={"error": {"code": "model_not_found"}})
        with pytest.raises(LLMError, match="GROQ_MODEL"):
            await engine._call_groq("prompt")

    @pytest.mark.asyncio
    async def test_an_empty_answer_is_an_error(self, transport):
        transport["handler"] = lambda r: httpx.Response(
            200, json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
        )
        with pytest.raises(LLMError, match="no answer"):
            await engine._call_groq("prompt")


@pytest.fixture
def claude(monkeypatch):
    """
    Serve the Anthropic SDK from a handler the test controls.

    The SDK runs on httpx2, so the httpx fixture above cannot see it; the
    client factory is swapped for one whose transport is a MockTransport.
    """
    import anthropic
    import httpx2

    state = {"handler": None, "requests": []}

    def handler(request):
        state["requests"].append(request)
        return state["handler"](request)

    def factory():
        return anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "anthropic-key-abc123")
    monkeypatch.setattr(engine, "_anthropic_client", factory)
    state["httpx2"] = httpx2
    return state


def claude_message(content, stop_reason="end_turn"):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": settings.ANTHROPIC_MODEL,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


class TestAnthropic:
    @pytest.mark.asyncio
    async def test_a_normal_answer_is_returned(self, claude):
        h = claude["httpx2"]
        claude["handler"] = lambda r: h.Response(
            200, json=claude_message([{"type": "text", "text": '{"ok": true}'}])
        )
        assert await engine._call_anthropic("prompt") == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_a_thinking_block_first_does_not_hide_the_answer(self, claude):
        """Current models think before answering; content[0] is not the text."""
        h = claude["httpx2"]
        claude["handler"] = lambda r: h.Response(
            200,
            json=claude_message([
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": '{"ok": true}'},
            ]),
        )
        assert await engine._call_anthropic("prompt") == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_the_request_uses_the_configured_model_and_no_sampling_params(self, claude, monkeypatch):
        import json as _json

        monkeypatch.setattr(settings, "ANTHROPIC_MODEL", "claude-test-model")
        h = claude["httpx2"]
        claude["handler"] = lambda r: h.Response(
            200, json=claude_message([{"type": "text", "text": "{}"}])
        )
        await engine._call_anthropic("prompt", temperature=0.3)
        sent = claude["requests"][0]
        body = _json.loads(sent.content)
        assert "anthropic-key-abc123" in (
            sent.headers.get("authorization", "") + sent.headers.get("x-api-key", "")
        )
        assert sent.headers["anthropic-version"]
        assert body["model"] == "claude-test-model"
        # Current models answer a non-default temperature with a 400.
        assert "temperature" not in body
        assert body["max_tokens"] >= 16000

    @pytest.mark.asyncio
    async def test_a_rate_limit_says_so(self, claude):
        h = claude["httpx2"]
        claude["handler"] = lambda r: h.Response(
            429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
        )
        with pytest.raises(LLMError, match="rate limit"):
            await engine._call_anthropic("prompt")

    @pytest.mark.asyncio
    async def test_a_retired_model_is_named_in_the_error(self, claude):
        h = claude["httpx2"]
        claude["handler"] = lambda r: h.Response(
            404, json={"type": "error", "error": {"type": "not_found_error", "message": "model"}}
        )
        with pytest.raises(LLMError, match="ANTHROPIC_MODEL"):
            await engine._call_anthropic("prompt")

    @pytest.mark.asyncio
    async def test_a_refusal_is_an_error_not_an_empty_report(self, claude):
        h = claude["httpx2"]
        claude["handler"] = lambda r: h.Response(
            200, json=claude_message([], stop_reason="refusal")
        )
        with pytest.raises(LLMError, match="refusal"):
            await engine._call_anthropic("prompt")

    @pytest.mark.asyncio
    async def test_an_answer_with_no_text_is_an_error(self, claude):
        h = claude["httpx2"]
        claude["handler"] = lambda r: h.Response(200, json=claude_message([]))
        with pytest.raises(LLMError, match="Unexpected Anthropic response"):
            await engine._call_anthropic("prompt")


class TestDispatcherOverTheWire:
    @pytest.mark.asyncio
    async def test_gemini_answers_and_the_others_are_never_called(self, transport):
        hosts = []

        def handler(request):
            hosts.append(request.url.host)
            return httpx.Response(200, json=gemini_body('{"result": 1}'))

        transport["handler"] = handler
        assert await engine.llm_call("prompt") == {"result": 1}
        assert hosts == ["generativelanguage.googleapis.com"]

    @pytest.mark.asyncio
    async def test_a_rate_limited_gemini_moves_straight_to_groq(self, transport, monkeypatch):
        """A rate limit is not something a retry fixes, so the dispatcher
        must not spend its backoff before giving up on that provider."""
        slept = []

        async def no_sleep(seconds):
            slept.append(seconds)

        monkeypatch.setattr(engine.asyncio, "sleep", no_sleep)
        hosts = []

        def handler(request):
            hosts.append(request.url.host)
            if "googleapis" in request.url.host:
                return httpx.Response(429)
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"via": "groq"}'}}]})

        transport["handler"] = handler
        assert await engine.llm_call("prompt") == {"via": "groq"}
        # Each configured Gemini model is asked once, then Groq.
        assert hosts == ["generativelanguage.googleapis.com"] * len(engine.gemini_models()) + ["api.groq.com"]
        assert slept == []

    @pytest.mark.asyncio
    async def test_a_transient_failure_is_retried_on_the_same_provider(self, transport, monkeypatch):
        async def no_sleep(seconds):
            return None

        monkeypatch.setattr(engine.asyncio, "sleep", no_sleep)
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503)
            return httpx.Response(200, json=gemini_body('{"result": 2}'))

        transport["handler"] = handler
        assert await engine.llm_call("prompt") == {"result": 2}
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_unparseable_json_moves_to_the_next_provider(self, transport, monkeypatch):
        async def no_sleep(seconds):
            return None

        monkeypatch.setattr(engine.asyncio, "sleep", no_sleep)
        hosts = []

        def handler(request):
            hosts.append(request.url.host)
            if "googleapis" in request.url.host:
                return httpx.Response(200, json=gemini_body("I'm sorry, I can't help with that."))
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"via": "groq"}'}}]})

        transport["handler"] = handler
        assert await engine.llm_call("prompt") == {"via": "groq"}
        assert hosts == ["generativelanguage.googleapis.com"] * len(engine.gemini_models()) + ["api.groq.com"]

    @pytest.mark.asyncio
    async def test_a_retired_first_gemini_model_hands_over_to_the_second(self, transport, monkeypatch):
        monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-retired,gemini-3.5-flash-lite")
        seen = []

        def handler(request):
            seen.append(request.url.path)
            if "gemini-retired" in request.url.path:
                return httpx.Response(404)
            return httpx.Response(200, json=gemini_body('{"via": "lite"}'))

        transport["handler"] = handler
        assert await engine.llm_call("prompt") == {"via": "lite"}
        assert len(seen) == 2, "a retired model must not be retried"

    @pytest.mark.asyncio
    async def test_every_provider_failing_reports_the_last_error(self, transport, monkeypatch):
        async def no_sleep(seconds):
            return None

        monkeypatch.setattr(engine.asyncio, "sleep", no_sleep)
        transport["handler"] = lambda r: httpx.Response(429)
        with pytest.raises(LLMError, match="All LLM providers failed"):
            await engine.llm_call("prompt")

    @pytest.mark.asyncio
    async def test_json_wrapped_in_prose_or_fences_is_still_read(self, transport):
        transport["handler"] = lambda r: httpx.Response(
            200,
            json=gemini_body('Here is the result:\n```json\n{"name": "Anita"}\n```\nHope that helps!'),
        )
        assert await engine.llm_call("prompt") == {"name": "Anita"}
