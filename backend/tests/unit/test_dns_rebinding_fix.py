"""
Tests for the DNS-rebinding fix in app/services/verify/ssrf_guard.py.

Background: is_public_http_url() validates a hostname's resolved IP at
check-time, but the HTTP request that follows re-resolves DNS moments
later — a gap an attacker controlling their own DNS (with a very short
TTL) could exploit: first lookup returns a public IP (passes
validation), second lookup (used for the real connection) returns an
internal address. pinned_dns()/safe_fetch() close this by resolving
once, validating that result, and forcing the actual connection to use
exactly that IP.

These tests use a REAL local HTTP server and REAL socket connections
(via httpx) rather than mocking socket.getaddrinfo's caller — mocking
would have hidden the actual bug found during development: httpx's
async client passes `host` to socket.getaddrinfo as BYTES, not str, and
a naive string-equality check against it silently never matches,
silently falling through to an unpinned lookup instead of raising
anything. A real end-to-end request is the only way to catch that class
of bug with confidence.
"""

import socket
import threading
import http.server
import contextlib

import httpx
import pytest

from app.services.verify.ssrf_guard import pinned_dns, safe_fetch, is_public_http_url


class _OkHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"pinned-ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def local_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _OkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    thread.join(timeout=2)


async def test_pinned_dns_resolves_the_hostname_to_the_pinned_ip(local_server):
    """
    The core mechanism: with a fake hostname pinned to 127.0.0.1, an httpx
    request to that fake hostname must actually reach the local server —
    proving the pin is honored by the real async connection path (not
    just by a mocked call site).
    """
    fake_host = "pinned-test.hirelens.invalid"
    async with httpx.AsyncClient() as client:
        with pinned_dns(fake_host, {"127.0.0.1"}):
            r = await client.get(f"http://{fake_host}:{local_server}/")
    assert r.status_code == 200
    assert r.text == "pinned-ok"


async def test_pinned_dns_does_not_affect_other_hostnames(local_server):
    """Only the pinned hostname is intercepted — everything else must
    keep resolving normally (a real, unrelated lookup)."""
    fake_host = "pinned-test-2.hirelens.invalid"
    with pinned_dns(fake_host, {"127.0.0.1"}):
        # "localhost" is not the pinned hostname — must resolve for real,
        # not be redirected to whatever fake_host was pinned to.
        infos = socket.getaddrinfo("localhost", None)
    assert any(info[4][0] in ("127.0.0.1", "::1") for info in infos)


def test_pinned_dns_restores_the_real_resolver_on_exit(local_server):
    real = socket.getaddrinfo
    with pinned_dns("whatever.hirelens.invalid", {"127.0.0.1"}):
        assert socket.getaddrinfo is not real
    assert socket.getaddrinfo is real


async def test_safe_fetch_rejects_a_hostname_that_resolves_to_a_private_ip():
    """
    safe_fetch() must refuse to even attempt a connection when the
    hostname resolves somewhere private — this is the existing SSRF
    check, now run as part of the same atomic validate-and-pin call.
    """
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            # "localhost" is explicitly blocklisted regardless of what it
            # resolves to.
            await safe_fetch(client, "http://localhost:9999/")


async def test_safe_fetch_succeeds_against_a_real_reachable_public_style_host(local_server, monkeypatch):
    """
    End-to-end: point safe_fetch() at a hostname that legitimately
    resolves to a public-looking address (loopback is used here as a
    stand-in, since this suite has no route to the real internet) and
    confirm it both validates AND successfully fetches through the
    pinned connection in one call.
    """
    # is_public_http_url()/safe_fetch() block loopback in the real
    # blocklist (correctly, for production) — for this test we only want
    # to prove the pin-then-fetch mechanism works end-to-end, so patch
    # just the IP-classification step to treat our test server's address
    # as "public" for this one call, the same way a real public IP would
    # be treated. The pinning logic under test is untouched by this.
    import app.services.verify.ssrf_guard as guard

    monkeypatch.setattr(guard, "_validated_ips", lambda hostname: {"127.0.0.1"})
    monkeypatch.setattr(guard, "_hostname_allowed", lambda h: True)

    async with httpx.AsyncClient() as client:
        r = await safe_fetch(client, f"http://safe-fetch-test.hirelens.invalid:{local_server}/")
    assert r.status_code == 200
    assert r.text == "pinned-ok"
