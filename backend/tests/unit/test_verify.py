"""
HireLens — Public Data Verification (Feature 3) Unit Tests
Run: cd backend && python -m pytest tests/unit/test_verify.py -v
"""
import sys
import os
import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── GitHub: username extraction ─────────────────────────────────────────────
class TestExtractUsername:
    def setup_method(self):
        from app.services.verify.github_verify import extract_username
        self.extract = extract_username

    def test_full_url(self):
        assert self.extract("https://github.com/octocat") == "octocat"

    def test_url_with_trailing_slash(self):
        assert self.extract("github.com/octocat/") == "octocat"

    def test_bare_username(self):
        assert self.extract("octocat") == "octocat"

    def test_none_input(self):
        assert self.extract(None) is None

    def test_empty_string(self):
        assert self.extract("") is None

    def test_garbage_with_spaces_rejected(self):
        assert self.extract("not a username at all") is None


# ── GitHub: skill/evidence matching ─────────────────────────────────────────
class TestSkillEvidenceMatch:
    def setup_method(self):
        from app.services.verify.github_verify import _skill_matches_evidence
        self.match = _skill_matches_evidence

    def test_exact_match_case_insensitive(self):
        assert self.match("Python", {"python"}) is True

    def test_substring_match(self):
        assert self.match("JavaScript", {"javascript"}) is True

    def test_matches_against_topic_or_description_term(self):
        assert self.match("Kubernetes", {"kubernetes", "helm charts"}) is True

    def test_no_match(self):
        assert self.match("Kubernetes", {"python"}) is False

    def test_empty_strings(self):
        assert self.match("", {"python"}) is False
        assert self.match("Python", set()) is False


# ── Company: domain guessing ────────────────────────────────────────────────
class TestGuessDomain:
    def setup_method(self):
        from app.services.verify.company_verify import _guess_domain
        self.guess = self.guess = _guess_domain

    def test_strips_corporate_suffix(self):
        assert self.guess("Acme Inc") == "acme.com"

    def test_multi_word_company(self):
        assert self.guess("Bright Data Solutions") == "brightdata.com"

    def test_empty_returns_none(self):
        assert self.guess("") is None

    def test_only_stopwords_returns_none(self):
        assert self.guess("The Company Ltd") is None


# ── Certification: URL extraction ───────────────────────────────────────────
class TestExtractCertUrl:
    def setup_method(self):
        from app.services.verify.certification_verify import _extract_url
        self.extract = _extract_url

    def test_finds_embedded_url(self):
        text = "AWS Certified Solutions Architect - https://credly.com/badges/abc123"
        assert self.extract(text) == "https://credly.com/badges/abc123"

    def test_no_url_returns_none(self):
        assert self.extract("AWS Certified Solutions Architect") is None

    def test_strips_trailing_punctuation(self):
        text = "See https://example.com/cert."
        assert self.extract(text) == "https://example.com/cert"


# ── GitHub: full async flow with mocked HTTP ────────────────────────────────
class TestVerifyGithubMocked:
    @pytest.mark.asyncio
    async def test_no_username_short_circuits(self):
        from app.services.verify.github_verify import verify_github
        result = await verify_github(None, ["Python"])
        assert result["status"] == "no_username"

    @pytest.mark.asyncio
    async def test_profile_not_found(self, monkeypatch):
        from app.services.verify import github_verify

        class FakeResponse:
            status_code = 404
            is_success = False

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs): return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
        result = await github_verify.verify_github("ghost-user-xyz", ["Python"])
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_verified_skill_from_full_language_breakdown(self, monkeypatch):
        """Proves the FULL per-repo language breakdown is used, not just each
        repo's single primary language — a Docker skill hidden inside a
        Python-primary repo should still be found."""
        from app.services.verify import github_verify

        class ProfileResponse:
            status_code = 200
            is_success = True
            def json(self): return {"public_repos": 2, "html_url": "https://github.com/dev", "created_at": "2019-01-01T00:00:00Z", "avatar_url": "x"}

        class ReposResponse:
            status_code = 200
            is_success = True
            def json(self):
                return [
                    {"name": "api-service", "language": "Python", "fork": False, "topics": ["backend"], "description": "REST API"},
                    {"name": "ml-pipeline", "language": "Python", "fork": False, "topics": [], "description": ""},
                ]

        class LanguagesResponse:
            status_code = 200
            is_success = True
            def __init__(self, langs): self._langs = langs
            def json(self): return self._langs

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs):
                if url.endswith("/dev"):
                    return ProfileResponse()
                if url.endswith("/repos"):
                    return ReposResponse()
                if "api-service/languages" in url:
                    # Docker is hidden here — NOT the repo's primary language
                    return LanguagesResponse({"Python": 40000, "Dockerfile": 500})
                if "ml-pipeline/languages" in url:
                    return LanguagesResponse({"Python": 90000, "Jupyter Notebook": 12000})
                return LanguagesResponse({})

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
        result = await github_verify.verify_github("dev", ["Python", "Docker", "Kubernetes"])
        assert result["status"] == "verified"
        assert "Python" in result["verified_skills"]
        assert "Docker" in result["verified_skills"], "Docker was hidden inside a Python-primary repo — full language breakdown should still catch it"
        assert "Kubernetes" in result["unverified_skills"]

    @pytest.mark.asyncio
    async def test_topic_evidence_matches_skill_not_in_any_language(self, monkeypatch):
        """A skill like 'Kubernetes' often shows up as a repo TOPIC, not a language."""
        from app.services.verify import github_verify

        class ProfileResponse:
            status_code = 200
            is_success = True
            def json(self): return {"public_repos": 1, "html_url": "x", "created_at": "2020-01-01T00:00:00Z", "avatar_url": "x"}

        class ReposResponse:
            status_code = 200
            is_success = True
            def json(self):
                return [{"name": "infra", "language": "HCL", "fork": False, "topics": ["kubernetes", "terraform"], "description": ""}]

        class LanguagesResponse:
            status_code = 200
            is_success = True
            def json(self): return {"HCL": 5000}

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs):
                if url.endswith("/dev2"):
                    return ProfileResponse()
                if url.endswith("/repos"):
                    return ReposResponse()
                return LanguagesResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
        result = await github_verify.verify_github("dev2", ["Kubernetes"])
        assert "Kubernetes" in result["verified_skills"]


# ── Education: mocked registry lookup ───────────────────────────────────────
class TestVerifyEducationMocked:
    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        from app.services.verify.education_verify import verify_education
        assert await verify_education([]) == []

    @pytest.mark.asyncio
    async def test_missing_institution_skipped(self):
        from app.services.verify.education_verify import verify_education
        result = await verify_education([{"institution": ""}])
        assert result[0]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_verified_match(self, monkeypatch):
        from app.services.verify import education_verify

        class FakeResponse:
            is_success = True
            content = b"[]"
            def json(self): return [{"name": "MIT", "country": "United States", "domains": ["mit.edu"]}]

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs): return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
        result = await education_verify.verify_education([{"institution": "MIT"}])
        assert result[0]["status"] == "verified"
        assert result[0]["domain"] == "mit.edu"

    @pytest.mark.asyncio
    async def test_retries_with_expanded_abbreviation_when_raw_name_fails(self, monkeypatch):
        """'IIT Delhi' should retry as 'Indian Institute of Technology Delhi'
        when the raw abbreviation finds nothing — this is the exact case that
        was silently failing before."""
        from app.services.verify import education_verify

        class EmptyResponse:
            is_success = True
            content = b"[]"
            def json(self): return []

        class MatchResponse:
            is_success = True
            content = b"[...]"
            def json(self): return [{"name": "Indian Institute of Technology Delhi", "country": "India", "domains": ["iitd.ac.in"]}]

        calls = []

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, params=None, **kwargs):
                calls.append(params["name"])
                if "indian institute of technology" in params["name"].lower():
                    return MatchResponse()
                return EmptyResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
        result = await education_verify.verify_education([{"institution": "IIT Delhi"}])
        assert result[0]["status"] == "verified"
        assert result[0]["domain"] == "iitd.ac.in"
        assert len(calls) > 1, "should have retried with a broadened query, not given up after one miss"

    @pytest.mark.asyncio
    async def test_not_found_after_exhausting_all_retry_variants(self, monkeypatch):
        from app.services.verify import education_verify

        class EmptyResponse:
            is_success = True
            content = b"[]"
            def json(self): return []

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs): return EmptyResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
        result = await education_verify.verify_education([{"institution": "Totally Fictional University XYZ"}])
        assert result[0]["status"] == "not_found"
        assert "does NOT necessarily mean" in result[0]["note"]


# ── Ranking / merge safety in verify.py orchestrator ────────────────────────
class TestVerifyOrchestratorSafety:
    def test_safe_falls_back_on_exception(self):
        from app.api.v1.endpoints.verify import _safe
        fallback = {"status": "error"}
        assert _safe(ValueError("boom"), fallback) == fallback

    def test_safe_passes_through_normal_value(self):
        from app.api.v1.endpoints.verify import _safe
        value = {"status": "verified"}
        assert _safe(value, {"status": "error"}) == value
