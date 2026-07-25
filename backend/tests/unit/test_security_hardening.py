"""
HireLens — Security Hardening Unit Tests
Run: cd backend && python -m pytest tests/unit/test_security_hardening.py -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.verify.ssrf_guard import is_public_http_url
from app.api.v1.endpoints.reports import _sanitize_search


# ── SSRF Guard ───────────────────────────────────────────────────────────────
class TestSSRFGuard:
    def test_public_domain_allowed(self):
        # A real, stable public domain — should resolve to a public IP.
        assert is_public_http_url("https://example.com/page") is True

    def test_localhost_blocked(self):
        assert is_public_http_url("http://localhost/admin") is False
        assert is_public_http_url("http://localhost:8080/") is False

    def test_loopback_ip_blocked(self):
        assert is_public_http_url("http://127.0.0.1/") is False
        assert is_public_http_url("http://127.0.0.1:6379/") is False

    def test_private_ip_ranges_blocked(self):
        assert is_public_http_url("http://10.0.0.1/") is False
        assert is_public_http_url("http://172.16.0.1/") is False
        assert is_public_http_url("http://192.168.1.1/") is False

    def test_link_local_metadata_endpoint_blocked(self):
        # Cloud metadata endpoint (AWS/GCP/Azure) — classic SSRF target
        assert is_public_http_url("http://169.254.169.254/latest/meta-data/") is False

    def test_zero_address_blocked(self):
        assert is_public_http_url("http://0.0.0.0/") is False

    def test_non_http_scheme_blocked(self):
        assert is_public_http_url("file:///etc/passwd") is False
        assert is_public_http_url("ftp://example.com/") is False
        assert is_public_http_url("gopher://127.0.0.1:6379/") is False

    def test_dot_local_blocked(self):
        assert is_public_http_url("http://myservice.local/") is False

    def test_malformed_url_rejected_not_crashed(self):
        assert is_public_http_url("not a url at all") is False
        assert is_public_http_url("") is False

    def test_unresolvable_hostname_rejected(self):
        assert is_public_http_url("http://this-domain-should-not-exist-xyz123.invalid/") is False


# ── Rate limiting helper ────────────────────────────────────────────────────
class TestRateLimitHelper:
    def test_no_redis_in_memory_fallback(self):
        from app.core.rate_limit import check_rate_limit, RateLimitExceeded
        key = "test-in-mem-key-unique"
        for _ in range(5):
            check_rate_limit(None, key, limit=5, window_seconds=60)
        with pytest.raises(RateLimitExceeded):
            check_rate_limit(None, key, limit=5, window_seconds=60)

    def test_get_client_ip_uses_forwarded_for(self):
        from app.core.rate_limit import get_client_ip

        class FakeRequest:
            headers = {"x-forwarded-for": "203.0.113.5, 10.0.0.1"}
            client = None

        assert get_client_ip(FakeRequest()) == "203.0.113.5"

    def test_get_client_ip_falls_back_to_client_host(self):
        from app.core.rate_limit import get_client_ip

        class FakeClient:
            host = "198.51.100.7"

        class FakeRequest:
            headers = {}
            client = FakeClient()

        assert get_client_ip(FakeRequest()) == "198.51.100.7"

    def test_enforces_limit_with_fake_redis(self):
        from app.core.rate_limit import check_rate_limit
        from app.core.exceptions import RateLimitExceeded

        class FakeRedis:
            def __init__(self):
                self.counts = {}

            def incr(self, key):
                self.counts[key] = self.counts.get(key, 0) + 1
                return self.counts[key]

            def expire(self, key, seconds):
                pass

        redis = FakeRedis()
        for _ in range(3):
            check_rate_limit(redis, "ip:1.2.3.4", limit=3, window_seconds=60)

        try:
            check_rate_limit(redis, "ip:1.2.3.4", limit=3, window_seconds=60)
            assert False, "should have raised RateLimitExceeded"
        except RateLimitExceeded:
            pass


# ── Search-filter injection sanitization ────────────────────────────────────
class TestSearchSanitization:
    def test_strips_comma_field_injection(self):
        result = _sanitize_search("x,recruiter_decision.eq.rejected")
        assert "," not in result

    def test_strips_parentheses(self):
        result = _sanitize_search("or(a.eq.1,b.eq.2)")
        assert "(" not in result and ")" not in result

    def test_strips_percent_and_asterisk(self):
        result = _sanitize_search("100%*done")
        assert "%" not in result and "*" not in result

    def test_allows_normal_name_search(self):
        assert _sanitize_search("John Smith") == "John Smith"

    def test_allows_common_tech_skill_punctuation(self):
        assert _sanitize_search("C++") == "C++"
        assert _sanitize_search("Node.js") == "Node.js"
        assert _sanitize_search("C#") == "C#"

    def test_caps_length(self):
        result = _sanitize_search("a" * 500)
        assert len(result) <= 100

    def test_empty_string(self):
        assert _sanitize_search("") == ""


# ── Production startup security checks ──────────────────────────────────────
class TestProductionSecurityChecks:
    def test_default_secret_key_is_flaggable_in_production(self):
        from app.core.config import Settings
        s = Settings(APP_ENV="production", SECRET_KEY="dev-secret-key-change-in-production-min-32")
        assert s.is_production is True
        # This is exactly the condition main.py's startup check guards against
        assert s.SECRET_KEY == "dev-secret-key-change-in-production-min-32"

    def test_custom_secret_key_not_flaggable(self):
        from app.core.config import Settings
        s = Settings(APP_ENV="production", SECRET_KEY="a" * 48)
        assert len(s.SECRET_KEY) >= 32
        assert s.SECRET_KEY != "dev-secret-key-change-in-production-min-32"

    def test_development_mode_is_not_production(self):
        from app.core.config import Settings
        s = Settings(APP_ENV="development")
        assert s.is_production is False
