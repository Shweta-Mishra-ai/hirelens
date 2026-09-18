"""
Verification services under a mocked network.

These three modules decide whether a certification link, an employer
domain or an ATS export is real, and until now none of them had a test
that exercised the fetching path — the part that talks to the internet
and the part a malicious resume can steer. Every test here drives httpx
through a MockTransport, so the behaviour is pinned without a single
outbound packet.
"""

import httpx
import pytest

from app.services.verify import certification_verify, company_verify
from app.services.verify.ssrf_guard import is_public_http_url


def mock_client(monkeypatch, module, handler):
    """Point the module's httpx.AsyncClient at a scripted transport."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


def allow_all_urls(monkeypatch, module):
    """Skip DNS in the guard so tests can use invented hostnames."""
    monkeypatch.setattr(module, "is_public_http_url", lambda url: url.startswith(("http://", "https://")))


# ── Certifications ──────────────────────────────────────────────────────────


class TestCertificationVerification:
    @pytest.mark.asyncio
    async def test_no_certifications_returns_nothing(self):
        assert await certification_verify.verify_certifications([], "Anita Rao") == []

    @pytest.mark.asyncio
    async def test_cert_without_a_link_is_reported_as_unverifiable_not_fake(self, monkeypatch):
        mock_client(monkeypatch, certification_verify, lambda r: httpx.Response(200))
        out = await certification_verify.verify_certifications(
            ["AWS Certified Solutions Architect"], "Anita Rao"
        )
        assert out[0]["status"] == "no_link_provided"
        assert "no public verification link" in out[0]["note"].lower()

    @pytest.mark.asyncio
    async def test_name_on_the_page_verifies_the_certificate(self, monkeypatch):
        allow_all_urls(monkeypatch, certification_verify)
        mock_client(
            monkeypatch,
            certification_verify,
            lambda r: httpx.Response(200, text="<h1>Anita Rao</h1> AWS Certified"),
        )
        out = await certification_verify.verify_certifications(
            ["AWS Certified — https://credly.example/badges/abc123"], "Anita Rao"
        )
        assert out[0]["status"] == "verified_via_link"
        assert out[0]["url"] == "https://credly.example/badges/abc123"
        # The URL is stripped out of the displayed certificate name.
        assert out[0]["name"] == "AWS Certified"
        assert out[0]["note"] is None

    @pytest.mark.asyncio
    async def test_name_missing_from_the_page_is_not_claimed_as_verified(self, monkeypatch):
        allow_all_urls(monkeypatch, certification_verify)
        mock_client(
            monkeypatch,
            certification_verify,
            lambda r: httpx.Response(200, text="<h1>Someone Else</h1>"),
        )
        out = await certification_verify.verify_certifications(
            ["AWS Certified https://credly.example/x"], "Anita Rao"
        )
        assert out[0]["status"] == "link_reachable_name_not_confirmed"
        assert "wasn't found" in out[0]["note"]

    @pytest.mark.asyncio
    async def test_a_404_is_reported_with_its_status(self, monkeypatch):
        allow_all_urls(monkeypatch, certification_verify)
        mock_client(monkeypatch, certification_verify, lambda r: httpx.Response(404))
        out = await certification_verify.verify_certifications(
            ["Cert https://credly.example/gone"], "Anita Rao"
        )
        assert out[0]["status"] == "link_unreachable"
        assert "404" in out[0]["note"]

    @pytest.mark.asyncio
    async def test_a_network_error_is_reported_not_raised(self, monkeypatch):
        allow_all_urls(monkeypatch, certification_verify)

        def boom(request):
            raise httpx.ConnectError("no route", request=request)

        mock_client(monkeypatch, certification_verify, boom)
        out = await certification_verify.verify_certifications(
            ["Cert https://credly.example/x"], "Anita Rao"
        )
        assert out[0]["status"] == "link_unreachable"

    @pytest.mark.asyncio
    async def test_an_internal_link_is_refused_before_it_is_fetched(self, monkeypatch):
        fetched = []

        def handler(request):
            fetched.append(str(request.url))
            return httpx.Response(200, text="Anita Rao")

        mock_client(monkeypatch, certification_verify, handler)
        out = await certification_verify.verify_certifications(
            ["Cert http://169.254.169.254/latest/meta-data/"], "Anita Rao"
        )
        assert out[0]["status"] == "link_unreachable"
        assert "non-public address" in out[0]["note"]
        assert fetched == []

    @pytest.mark.asyncio
    async def test_a_redirect_into_the_metadata_service_is_stopped_mid_chain(self, monkeypatch):
        """The first hop is public; the second is not. The guard re-checks
        every hop, so the internal address is never requested."""
        seen = []

        def handler(request):
            seen.append(request.url.host)
            if request.url.host == "credly.example":
                return httpx.Response(302, headers={"location": "http://169.254.169.254/"})
            return httpx.Response(200, text="Anita Rao")

        mock_client(monkeypatch, certification_verify, handler)
        monkeypatch.setattr(
            certification_verify,
            "is_public_http_url",
            lambda url: "169.254.169.254" not in url and url.startswith(("http://", "https://")),
        )
        out = await certification_verify.verify_certifications(
            ["Cert https://credly.example/x"], "Anita Rao"
        )
        assert out[0]["status"] == "link_unreachable"
        assert "169.254.169.254" not in seen

    @pytest.mark.asyncio
    async def test_a_redirect_loop_gives_up_instead_of_hanging(self, monkeypatch):
        allow_all_urls(monkeypatch, certification_verify)
        hops = []

        def handler(request):
            hops.append(1)
            return httpx.Response(302, headers={"location": "https://credly.example/next"})

        mock_client(monkeypatch, certification_verify, handler)
        out = await certification_verify.verify_certifications(
            ["Cert https://credly.example/x"], "Anita Rao"
        )
        assert out[0]["status"] == "link_unreachable"
        assert len(hops) <= certification_verify.MAX_REDIRECT_HOPS + 1

    @pytest.mark.asyncio
    async def test_only_the_first_ten_certificates_are_fetched(self, monkeypatch):
        allow_all_urls(monkeypatch, certification_verify)
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200, text="Anita Rao")

        mock_client(monkeypatch, certification_verify, handler)
        certs = [f"Cert {i} https://credly.example/{i}" for i in range(25)]
        out = await certification_verify.verify_certifications(certs, "Anita Rao")
        assert len(out) == certification_verify.MAX_CERTS
        assert len(calls) == certification_verify.MAX_CERTS

    @pytest.mark.asyncio
    async def test_a_dict_shaped_certificate_is_handled(self, monkeypatch):
        mock_client(monkeypatch, certification_verify, lambda r: httpx.Response(200))
        out = await certification_verify.verify_certifications(
            [{"name": "PMP Certification"}], "Anita Rao"
        )
        assert out[0]["name"] == "PMP Certification"
        assert out[0]["status"] == "no_link_provided"

    @pytest.mark.asyncio
    async def test_no_candidate_name_means_no_verified_claim(self, monkeypatch):
        allow_all_urls(monkeypatch, certification_verify)
        mock_client(monkeypatch, certification_verify, lambda r: httpx.Response(200, text="anything"))
        out = await certification_verify.verify_certifications(
            ["Cert https://credly.example/x"], None
        )
        assert out[0]["status"] == "link_reachable_name_not_confirmed"


# ── Employers ───────────────────────────────────────────────────────────────


class TestCompanyVerification:
    def test_domain_guessing_drops_legal_suffixes(self):
        assert company_verify._guess_domain("Acme Technologies Pvt Ltd") == "acme.com"
        assert company_verify._guess_domain("The Widget Company") == "widget.com"
        assert company_verify._guess_domain("Zeta & Co") == "zeta.com"

    def test_a_name_that_is_only_stopwords_is_not_guessable(self):
        assert company_verify._guess_domain("Inc LLC Ltd") is None
        assert company_verify._guess_domain("") is None
        assert company_verify._guess_domain("!!!") is None

    @pytest.mark.asyncio
    async def test_no_experience_returns_nothing(self):
        assert await company_verify.verify_experience_companies([]) == []

    @pytest.mark.asyncio
    async def test_a_live_domain_is_reported_as_found(self, monkeypatch):
        allow_all_urls(monkeypatch, company_verify)
        mock_client(monkeypatch, company_verify, lambda r: httpx.Response(200))
        out = await company_verify.verify_experience_companies([{"company": "Acme Labs"}])
        assert out[0]["status"] == "domain_found"
        assert out[0]["domain_checked"] == "acme.com"
        # A note is attached on the positive case too. A live website shows the
        # employer is real; it is not evidence the candidate worked there, and
        # a green row with no caveat beside an employment claim reads as
        # though it is.
        assert "does not confirm the candidate worked there" in out[0]["note"]

    @pytest.mark.asyncio
    async def test_a_missing_domain_is_a_weak_signal_not_a_red_flag(self, monkeypatch):
        allow_all_urls(monkeypatch, company_verify)
        mock_client(monkeypatch, company_verify, lambda r: httpx.Response(404))
        out = await company_verify.verify_experience_companies([{"company": "Acme Labs"}])
        assert out[0]["status"] == "domain_not_found"
        assert "weak signal" in out[0]["note"]

    @pytest.mark.asyncio
    async def test_https_failure_falls_back_to_http(self, monkeypatch):
        allow_all_urls(monkeypatch, company_verify)
        schemes = []

        def handler(request):
            schemes.append(request.url.scheme)
            return httpx.Response(200 if request.url.scheme == "http" else 500)

        mock_client(monkeypatch, company_verify, handler)
        out = await company_verify.verify_experience_companies([{"company": "Acme"}])
        assert schemes == ["https", "http"]
        assert out[0]["status"] == "domain_found"

    @pytest.mark.asyncio
    async def test_a_connection_error_is_not_fatal(self, monkeypatch):
        allow_all_urls(monkeypatch, company_verify)

        def boom(request):
            raise httpx.ConnectTimeout("timed out", request=request)

        mock_client(monkeypatch, company_verify, boom)
        out = await company_verify.verify_experience_companies([{"company": "Acme"}])
        assert out[0]["status"] == "domain_not_found"

    @pytest.mark.asyncio
    async def test_a_redirect_to_an_internal_address_is_not_followed(self, monkeypatch):
        seen = []

        def handler(request):
            seen.append(request.url.host)
            if request.url.host == "acme.com":
                return httpx.Response(301, headers={"location": "http://127.0.0.1:8000/admin"})
            return httpx.Response(200)

        mock_client(monkeypatch, company_verify, handler)
        monkeypatch.setattr(
            company_verify,
            "is_public_http_url",
            lambda url: "127.0.0.1" not in url and url.startswith(("http://", "https://")),
        )
        out = await company_verify.verify_experience_companies([{"company": "Acme"}])
        assert out[0]["status"] == "domain_not_found"
        assert "127.0.0.1" not in seen

    @pytest.mark.asyncio
    async def test_a_redirect_without_a_location_header_stops(self, monkeypatch):
        allow_all_urls(monkeypatch, company_verify)
        mock_client(monkeypatch, company_verify, lambda r: httpx.Response(302))
        out = await company_verify.verify_experience_companies([{"company": "Acme"}])
        assert out[0]["status"] == "domain_not_found"

    @pytest.mark.asyncio
    async def test_blank_and_malformed_entries_are_skipped(self, monkeypatch):
        allow_all_urls(monkeypatch, company_verify)
        mock_client(monkeypatch, company_verify, lambda r: httpx.Response(200))
        out = await company_verify.verify_experience_companies(
            [{"company": ""}, {"title": "Engineer"}, "not-a-dict", {"company": "Inc"}]
        )
        assert [r["status"] for r in out] == ["skipped", "skipped", "skipped", "skipped"]
        assert "Could not derive" in out[3]["note"]

    @pytest.mark.asyncio
    async def test_only_the_first_ten_employers_are_checked(self, monkeypatch):
        allow_all_urls(monkeypatch, company_verify)
        mock_client(monkeypatch, company_verify, lambda r: httpx.Response(200))
        out = await company_verify.verify_experience_companies(
            [{"company": f"Company{i}"} for i in range(30)]
        )
        assert len(out) == company_verify.MAX_COMPANIES


# ── The guard itself ────────────────────────────────────────────────────────


class TestSsrfGuard:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/x",
            "http://127.0.0.1/x",
            "http://0.0.0.0/",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/",
            "http://printer.local/",
            "http://admin.internal/",
            "file:///etc/passwd",
            "ftp://example.com/x",
            "https://",
            "not a url at all",
        ],
    )
    def test_unsafe_urls_are_refused(self, url):
        assert is_public_http_url(url) is False

    def test_a_hostname_that_does_not_resolve_is_refused(self):
        assert is_public_http_url("https://this-host-does-not-exist.invalid/") is False

    def test_a_private_ip_literal_is_refused(self):
        for ip in ("10.0.0.5", "192.168.1.1", "172.16.0.1", "[::1]"):
            assert is_public_http_url(f"http://{ip}/") is False
