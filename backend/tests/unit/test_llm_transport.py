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
        assert payload["generationConfig"]["maxOutputTokens"] == 1234
        assert payload["generationConfig"]["responseMimeType"] == "application/json"

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
    async def test_a_connection_failure_never_leaks_the_api_key(self, transport):
        """The key is in the query string, so httpx puts it in the error
        text. It must not reach a log line or an error surfaced to a user."""

        def boom(request):
            raise httpx.ConnectError(f"failed connecting to {request.url}", request=request)

        transport["handler"] = boom
        with pytest.raises(LLMError) as err:
            await engine._call_gemini("prompt")
        assert "gemini-key-abc123" not in str(err.value)
        assert "********" in str(err.value)


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
        with pytest.raises(httpx.HTTPStatusError):
            await engine._call_groq("prompt")


class TestAnthropic:
    @pytest.mark.asyncio
    async def test_a_normal_answer_is_returned(self, transport):
        transport["handler"] = lambda r: httpx.Response(
            200, json={"content": [{"text": '{"ok": true}'}]}
        )
        assert await engine._call_anthropic("prompt") == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_the_request_carries_the_key_and_api_version(self, transport):
        transport["handler"] = lambda r: httpx.Response(200, json={"content": [{"text": "{}"}]})
        await engine._call_anthropic("prompt")
        sent = transport["requests"][0]
        assert sent.headers["x-api-key"] == "anthropic-key-abc123"
        assert sent.headers["anthropic-version"]

    @pytest.mark.asyncio
    async def test_a_rate_limit_says_so(self, transport):
        transport["handler"] = lambda r: httpx.Response(429)
        with pytest.raises(LLMError, match="rate limit"):
            await engine._call_anthropic("prompt")

    @pytest.mark.asyncio
    async def test_an_unexpected_envelope_is_an_error(self, transport):
        transport["handler"] = lambda r: httpx.Response(200, json={"content": []})
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
        assert hosts == ["generativelanguage.googleapis.com", "api.groq.com"]
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
        assert hosts == ["generativelanguage.googleapis.com", "api.groq.com"]

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
