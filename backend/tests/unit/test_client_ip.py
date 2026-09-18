"""
Whose address the rate limiter counts.

Rate limits are keyed on the caller's IP, and behind a proxy that address
comes from X-Forwarded-For — a header the caller also controls. Each proxy
APPENDS the address it saw, so the rightmost entries are the ones written by
infrastructure and everything to the left is whatever the caller chose to
send.

Read the leftmost entry and a caller mints a fresh bucket per request just by
changing a header: unlimited password guesses against sign-in, and unlimited
account creation. Only `TRUSTED_PROXY_HOPS` entries from the right count.
"""

import pytest

from app.core.config import settings
from app.core.rate_limit import get_client_ip

DIRECT = "10.1.2.3"          # what the socket reports — the proxy, in production
REAL = "203.0.113.77"        # the address the proxy actually observed
SPOOF = "198.51.100.1"       # whatever the caller put in the header


class FakeClient:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, xff=None, host=DIRECT):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = FakeClient(host) if host else None


@pytest.fixture
def one_hop(monkeypatch):
    """Render, Vercel — exactly one proxy in front."""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1, raising=False)


class TestBehindOneProxy:
    def test_the_address_the_proxy_saw_is_used(self, one_hop):
        assert get_client_ip(FakeRequest(REAL)) == REAL

    def test_a_spoofed_entry_is_ignored(self, one_hop):
        """The proxy appends, so the caller's value ends up on the left."""
        assert get_client_ip(FakeRequest(f"{SPOOF}, {REAL}")) == REAL

    def test_a_long_spoofed_chain_is_ignored(self, one_hop):
        chain = "1.1.1.1, 2.2.2.2, 3.3.3.3, " + REAL
        assert get_client_ip(FakeRequest(chain)) == REAL

    def test_rotating_the_spoof_does_not_change_the_key(self, one_hop):
        """The whole point: 25 different headers, one rate-limit bucket."""
        keys = {get_client_ip(FakeRequest(f"198.51.100.{i}, {REAL}")) for i in range(25)}
        assert keys == {REAL}

    def test_whitespace_is_tolerated(self, one_hop):
        assert get_client_ip(FakeRequest(f"  {SPOOF} ,   {REAL}  ")) == REAL

    def test_no_header_falls_back_to_the_socket(self, one_hop):
        assert get_client_ip(FakeRequest(None)) == DIRECT

    def test_a_junk_header_cannot_poison_the_key(self, one_hop):
        for junk in ("not-an-ip", "", ",,,", "<script>", "a" * 500):
            assert get_client_ip(FakeRequest(junk)) == DIRECT

    def test_an_ipv6_address_is_accepted(self, one_hop):
        assert get_client_ip(FakeRequest(f"{SPOOF}, 2001:db8::1")) == "2001:db8::1"

    def test_a_missing_client_is_survivable(self, one_hop):
        assert get_client_ip(FakeRequest(None, host=None)) == "unknown"


class TestBehindTwoProxies:
    @pytest.fixture(autouse=True)
    def two_hops(self, monkeypatch):
        """Cloudflare in front of Render, for example."""
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2, raising=False)

    def test_it_counts_past_both_proxies(self):
        assert get_client_ip(FakeRequest(f"{SPOOF}, {REAL}, 10.0.0.9")) == REAL

    def test_a_shorter_chain_than_configured_does_not_crash(self):
        assert get_client_ip(FakeRequest(REAL)) == REAL


class TestNoProxy:
    @pytest.fixture(autouse=True)
    def no_hops(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 0, raising=False)

    def test_the_header_is_ignored_entirely(self):
        """With nothing in front, the header is not evidence of anything —
        every entry in it was written by the caller."""
        assert get_client_ip(FakeRequest(f"{SPOOF}, {REAL}")) == DIRECT
        assert get_client_ip(FakeRequest(SPOOF)) == DIRECT
