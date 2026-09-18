"""
The keep-alive that stops a free-tier instance idle-sleeping.

Render spins a free instance down after roughly 15 minutes without traffic.
The first request afterwards then takes 30-60s while the container wakes,
which to anyone using the app is indistinguishable from it being down.

Two ways this used to fail silently:

  * BACKEND_URL pointing at localhost. The ping has to leave and re-enter
    through the public URL to count as traffic; a loopback ping logs success
    forever while the service sleeps anyway.
  * A ping that fails every time — wrong host, DNS gone — logged at WARNING
    and was never escalated, so nothing distinguished it from a working one
    until someone reported the app was down.
"""

import asyncio
import logging

import pytest

from app.core.config import settings
import app.main as main


def _run(coro, seconds: float = 0.5):
    """Run the loop briefly; it never returns on its own by design."""

    async def driver():
        task = asyncio.create_task(coro)
        await asyncio.sleep(seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(driver())


def _fast_loop(monkeypatch):
    """Run the real loop on a real clock, just a very short one."""
    monkeypatch.setattr(main, "KEEP_ALIVE_STARTUP_DELAY", 0)
    monkeypatch.setattr(main, "KEEP_ALIVE_SECONDS", 0.001)


class TestItRefusesToPingSomewhereUseless:
    def test_no_backend_url_says_what_will_happen(self, monkeypatch, caplog):
        monkeypatch.setattr(settings, "BACKEND_URL", "")
        with caplog.at_level(logging.WARNING):
            asyncio.run(main._keep_alive_loop())
        assert any("BACKEND_URL is not set" in r.message for r in caplog.records)

    @pytest.mark.parametrize(
        "url", ["http://localhost:8000", "http://127.0.0.1:8000", "localhost:8000"]
    )
    def test_a_local_backend_url_is_refused_not_silently_pinged(
        self, url, monkeypatch, caplog
    ):
        monkeypatch.setattr(settings, "BACKEND_URL", url)
        with caplog.at_level(logging.ERROR):
            asyncio.run(main._keep_alive_loop())
        assert any("local address" in r.message for r in caplog.records), (
            "pinging loopback keeps nothing awake, and logging success is worse "
            "than not running at all"
        )

    def test_a_bare_host_is_read_as_https(self, monkeypatch):
        """Render prints the host; someone pastes it without the scheme."""
        monkeypatch.setattr(settings, "BACKEND_URL", "hirelens-gjoe.onrender.com")
        _fast_loop(monkeypatch)
        seen = []

        class FakeClient:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                seen.append(url)

                class R:
                    status_code = 200

                return R()

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        _run(main._keep_alive_loop(), 0.3)
        assert seen, "no ping was attempted"
        assert seen[0] == "https://hirelens-gjoe.onrender.com/api/v1/health"


class TestRepeatedFailureIsEscalated:
    def _run_with_failing_pings(self, monkeypatch, caplog, failures: int):
        monkeypatch.setattr(settings, "BACKEND_URL", "https://svc.onrender.com")
        _fast_loop(monkeypatch)
        attempts = {"n": 0}

        class FakeClient:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                attempts["n"] += 1
                if attempts["n"] > failures:
                    raise asyncio.CancelledError()
                raise RuntimeError("name or service not known")

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        with caplog.at_level(logging.WARNING):
            _run(main._keep_alive_loop(), 0.4)
        return caplog.records

    def test_one_failure_is_only_a_warning(self, monkeypatch, caplog):
        records = self._run_with_failing_pings(monkeypatch, caplog, failures=1)
        assert any(r.levelno == logging.WARNING for r in records)
        assert not [r for r in records if r.levelno >= logging.CRITICAL]

    def test_three_in_a_row_is_critical_and_names_the_cause(self, monkeypatch, caplog):
        records = self._run_with_failing_pings(monkeypatch, caplog, failures=3)
        critical = [r for r in records if r.levelno >= logging.CRITICAL]
        assert critical, "a keep-alive failing every time must not stay at WARNING"
        assert any("idle-sleep" in r.message for r in critical)
        assert any("BACKEND_URL" in r.message for r in critical)


class TestAnErrorStatusCountsAsFailure:
    def test_a_404_ping_is_not_treated_as_success(self, monkeypatch, caplog):
        """A wrong path returns 404 happily; that keeps nothing awake either."""
        monkeypatch.setattr(settings, "BACKEND_URL", "https://svc.onrender.com")
        _fast_loop(monkeypatch)

        class FakeClient:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                class R:
                    status_code = 404

                return R()

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        with caplog.at_level(logging.WARNING):
            _run(main._keep_alive_loop(), 0.3)
        assert any("failed" in r.message for r in caplog.records)
