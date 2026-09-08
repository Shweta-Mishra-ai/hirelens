"""
HireLens — same-site / cross-site detection tests
Run: cd backend && python -m pytest tests/unit/test_site_detection.py -v

This decides the session cookie's SameSite/Secure/Partitioned attributes, so
getting it wrong in the "same-site" direction sets SameSite=Lax on a genuinely
cross-site cookie and silently logs everyone out on every page load. The
detection therefore has to err towards cross-site, and these tests pin that
direction down as much as they pin the happy paths.

The trap worth being explicit about: *.vercel.app and *.onrender.com are
public suffixes. `a.vercel.app` and `b.vercel.app` share their last two labels
but are entirely different sites, so a naive registrable-domain comparison
would call them same-site and break login.
"""

import pytest

from app.core.site import (
    is_same_site,
    registrable_domain,
    session_cookie_is_cross_site,
)
from app.core.config import settings


class TestRegistrableDomain:
    def test_plain_domain(self):
        assert registrable_domain("hirelens.com") == "hirelens.com"

    def test_subdomain_collapses_to_the_site(self):
        assert registrable_domain("api.hirelens.com") == "hirelens.com"
        assert registrable_domain("a.b.c.hirelens.com") == "hirelens.com"

    def test_public_suffix_host_keeps_the_customer_label(self):
        # Without the public-suffix list these would both be "vercel.app".
        assert registrable_domain("hirelens.vercel.app") == "hirelens.vercel.app"
        assert registrable_domain("hirelens-api.onrender.com") == "hirelens-api.onrender.com"

    def test_localhost(self):
        assert registrable_domain("localhost") == "localhost"


class TestIsSameSite:
    def test_subdomains_of_one_domain_are_same_site(self):
        assert is_same_site("https://app.hirelens.com", "https://api.hirelens.com") is True

    def test_apex_and_subdomain_are_same_site(self):
        assert is_same_site("https://hirelens.com", "https://api.hirelens.com") is True

    def test_two_different_domains_are_cross_site(self):
        assert is_same_site("https://hirelens.com", "https://hirelens-api.net") is False

    def test_vercel_plus_render_is_cross_site(self):
        """The current default deployment."""
        assert is_same_site(
            "https://hirelens-theta.vercel.app",
            "https://hirelens-api.onrender.com",
        ) is False

    def test_two_vercel_apps_are_cross_site(self):
        """The trap: same last two labels, completely different sites."""
        assert is_same_site("https://a.vercel.app", "https://b.vercel.app") is False

    def test_the_very_same_host_is_same_site(self):
        assert is_same_site("https://a.vercel.app", "https://a.vercel.app") is True

    def test_localhost_pair_is_same_site_regardless_of_port(self):
        """Ports do not affect a cookie's site — local dev must not be treated
        as cross-site, or the dev cookie would need Secure over plain http."""
        assert is_same_site("http://localhost:3000", "http://localhost:8000") is True

    def test_localhost_against_a_real_domain_is_cross_site(self):
        assert is_same_site("http://localhost:3000", "https://api.hirelens.com") is False

    def test_unknown_when_a_url_is_missing(self):
        """None, not False — 'not configured' is a different thing to say."""
        assert is_same_site("https://app.hirelens.com", "") is None
        assert is_same_site("", "") is None

    def test_trailing_dot_and_case_are_normalised(self):
        assert is_same_site("https://APP.Hirelens.com./", "https://api.hirelens.com") is True

    def test_bare_host_without_a_scheme(self):
        assert is_same_site("app.hirelens.com", "api.hirelens.com") is True


class TestSessionCookieIsCrossSite:
    def test_defaults_to_cross_site_when_backend_url_is_unset(self, monkeypatch):
        """Fail-safe: an unprovable case must degrade to the wider cookie,
        which is the known-working behaviour, not to the one that breaks login.
        """
        monkeypatch.setattr(settings, "SESSION_COOKIE_CROSS_SITE", None)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://hirelens.vercel.app")
        monkeypatch.setattr(settings, "BACKEND_URL", "")
        assert session_cookie_is_cross_site(settings) is True

    def test_detects_same_site_deployment(self, monkeypatch):
        monkeypatch.setattr(settings, "SESSION_COOKIE_CROSS_SITE", None)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.hirelens.com")
        monkeypatch.setattr(settings, "BACKEND_URL", "https://api.hirelens.com")
        assert session_cookie_is_cross_site(settings) is False

    def test_detects_cross_site_deployment(self, monkeypatch):
        monkeypatch.setattr(settings, "SESSION_COOKIE_CROSS_SITE", None)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://hirelens.vercel.app")
        monkeypatch.setattr(settings, "BACKEND_URL", "https://hirelens-api.onrender.com")
        assert session_cookie_is_cross_site(settings) is True

    def test_explicit_override_beats_detection(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.hirelens.com")
        monkeypatch.setattr(settings, "BACKEND_URL", "https://api.hirelens.com")
        monkeypatch.setattr(settings, "SESSION_COOKIE_CROSS_SITE", True)
        assert session_cookie_is_cross_site(settings) is True

        monkeypatch.setattr(settings, "SESSION_COOKIE_CROSS_SITE", False)
        assert session_cookie_is_cross_site(settings) is False


class TestCookieAttributesFollowDetection:
    """The payoff: moving to one domain must change the cookie with no code
    edit. These drive the real cookie helper, not just the detector."""

    def _header(self, monkeypatch, frontend, backend):
        from starlette.responses import Response
        from app.core.session_cookies import set_session_cookie

        monkeypatch.setattr(settings, "APP_ENV", "production")
        monkeypatch.setattr(settings, "SESSION_COOKIE_CROSS_SITE", None)
        monkeypatch.setattr(settings, "FRONTEND_URL", frontend)
        monkeypatch.setattr(settings, "BACKEND_URL", backend)

        response = Response()
        set_session_cookie(response, "a.token.value")
        return next(
            v.decode("latin-1")
            for k, v in response.raw_headers
            if k.lower() == b"set-cookie"
        )

    def test_cross_site_deployment_gets_the_wide_cookie(self, monkeypatch):
        header = self._header(
            monkeypatch, "https://hirelens.vercel.app", "https://hirelens-api.onrender.com"
        )
        assert "SameSite=none" in header
        assert "Secure" in header
        assert "Partitioned" in header

    def test_same_domain_deployment_drops_the_cross_site_attributes(self, monkeypatch):
        header = self._header(
            monkeypatch, "https://app.hirelens.com", "https://api.hirelens.com"
        )
        assert "SameSite=lax" in header
        # Still Secure — production is https — but no longer SameSite=None,
        # and Partitioned would be actively wrong here.
        assert "Secure" in header
        assert "Partitioned" not in header

    def test_unset_backend_url_still_gets_the_working_cookie(self, monkeypatch):
        header = self._header(monkeypatch, "https://hirelens.vercel.app", "")
        assert "SameSite=none" in header
        assert "Partitioned" in header
