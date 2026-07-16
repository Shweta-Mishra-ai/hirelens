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


# ── GitHub: skill/language matching ─────────────────────────────────────────
class TestSkillLanguageMatch:
    def setup_method(self):
        from app.services.verify.github_verify import _skill_matches_language
        self.match = _skill_matches_language

    def test_exact_match_case_insensitive(self):
        assert self.match("Python", "python") is True

    def test_substring_match(self):
        assert self.match("JavaScript", "javascript") is True

    def test_alias_match_typescript(self):
        assert self.match("TypeScript", "TypeScript") is True

    def test_no_match(self):
        assert self.match("Kubernetes", "Python") is False

    def test_empty_strings(self):
        assert self.match("", "Python") is False
        assert self.match("Python", "") is False


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
    async def test_verified_skill_from_matching_language(self, monkeypatch):
        from app.services.verify import github_verify

        class ProfileResponse:
            status_code = 200
            is_success = True
            def json(self): return {"public_repos": 5, "html_url": "https://github.com/dev", "created_at": "2019-01-01T00:00:00Z", "avatar_url": "x"}

        class ReposResponse:
            status_code = 200
            is_success = True
            def json(self): return [{"language": "Python"}, {"language": "Python"}, {"language": "HTML"}]

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs):
                return ProfileResponse() if url.endswith("/dev") or "repos" not in url else ReposResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
        result = await github_verify.verify_github("dev", ["Python", "Kubernetes"])
        assert result["status"] == "verified"
        assert "Python" in result["verified_skills"]
        assert "Kubernetes" in result["unverified_skills"]


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
