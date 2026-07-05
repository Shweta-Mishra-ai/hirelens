"""
HireLens — Unit Tests
Run: cd backend && python -m pytest tests/ -v
"""
import pytest
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# ── Test: JSON extraction ─────────────────────────────────────────────────────
class TestExtractJSON:
    def setup_method(self):
        from app.services.ai.engine import extract_json
        self.extract = extract_json

    def test_clean_json(self):
        result = self.extract('{"key": "value", "num": 42}')
        assert result == {"key": "value", "num": 42}

    def test_json_with_markdown_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        result = self.extract(raw)
        assert result == {"key": "value"}

    def test_json_with_fence_no_language(self):
        raw = '```\n{"key": "value"}\n```'
        result = self.extract(raw)
        assert result == {"key": "value"}

    def test_json_embedded_in_prose(self):
        raw = 'Here is the result: {"key": "value"} as requested.'
        result = self.extract(raw)
        assert result == {"key": "value"}

    def test_nested_json(self):
        raw = '{"outer": {"inner": [1, 2, 3]}, "flag": true}'
        result = self.extract(raw)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_invalid_json_raises(self):
        from app.core.exceptions import LLMError
        with pytest.raises(ValueError):
            self.extract("this is not json at all")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            self.extract("")


# ── Test: Engine merge ────────────────────────────────────────────────────────
class TestEngineScore:
    def setup_method(self):
        from app.services.ai.engine import AnalysisEngine
        self.engine = AnalysisEngine()

    def test_merge_basic(self):
        extracted = {
            "candidate": {"name": "Test User", "email": "t@test.com", "phone": None, "location": None},
            "skills": {"all_claimed": ["Python"], "from_experience": ["Python"], "from_projects": [], "keyword_stuffing_risk": "none", "primary_domain": "Software"},
            "experience": [{"role": "Dev", "company": "ACME", "period": "2020-2024", "is_verifiable": True}],
            "education": [],
            "projects": [],
            "certifications": [],
        }
        analysis = {
            "credibility": {
                "overall": 82,
                "recommendation": "recommended",
                "confidence": "high",
                "sub_scores": {"timeline": 90, "skills_consistency": 80, "education": 85, "project_authenticity": 75, "resume_quality": 88},
                "score_rationale": {},
            },
            "skills_verification": {"verified_by_evidence": ["Python"], "unverified": [], "domain_spread_concern": False, "domain_spread_note": None},
            "timeline_gaps": [],
            "flags": [],
            "positive_signals": [{"title": "Good", "description": "Strong candidate"}],
            "interview_questions": [{"question": "Tell me about Python?", "rationale": "Core skill", "targets_flag": None, "category": "technical"}],
            "summary": "Strong candidate with good Python skills.",
            "one_liner": "Recommended Python developer.",
        }
        result = self.engine._merge(extracted, analysis)
        assert result["credibility"]["overall"] == 82
        assert result["credibility"]["recommendation"] == "recommended"
        assert result["skills"]["verified_by_evidence"] == ["Python"]
        assert result["recruiter_decision"] is None
        assert len(result["interview_questions"]) == 1

    def test_merge_handles_missing_fields(self):
        """merge() should not crash on empty/missing LLM outputs"""
        result = self.engine._merge({}, {})
        assert result["credibility"]["overall"] == 0
        assert result["credibility"]["recommendation"] == "high_risk"
        assert result["flags"] == []
        assert result["skills"]["all_claimed"] == []

    def test_merge_clamps_score(self):
        analysis = {
            "credibility": {"overall": 999, "recommendation": "recommended", "sub_scores": {}, "confidence": "high"},
            "skills_verification": {},
        }
        result = self.engine._merge({}, analysis)
        assert result["credibility"]["overall"] == 100

    def test_merge_recommendation_from_score(self):
        """If recommendation field missing/invalid, derive from score"""
        analysis = {
            "credibility": {"overall": 82, "recommendation": "INVALID_VALUE", "sub_scores": {}, "confidence": "high"},
            "skills_verification": {},
        }
        result = self.engine._merge({}, analysis)
        assert result["credibility"]["recommendation"] == "recommended"

    def test_merge_recommendation_manual_review(self):
        analysis = {
            "credibility": {"overall": 62, "recommendation": None, "sub_scores": {}, "confidence": "medium"},
            "skills_verification": {},
        }
        result = self.engine._merge({}, analysis)
        assert result["credibility"]["recommendation"] == "manual_review"


# ── Test: Document parser ─────────────────────────────────────────────────────
class TestDocumentParser:
    def setup_method(self):
        from app.services.parser.document_parser import extract_text, _clean_text
        self.extract = extract_text
        self.clean = _clean_text

    def test_unsupported_type_raises(self):
        from app.core.exceptions import UnsupportedFileType
        with pytest.raises(UnsupportedFileType):
            self.extract(b"fake content", "image/jpeg", "photo.jpg")

    def test_empty_file_raises(self):
        from app.core.exceptions import ParseError
        with pytest.raises(ParseError):
            self.extract(b"", "application/pdf", "empty.pdf")

    def test_clean_text_normalizes_whitespace(self):
        result = self.clean("hello   world\n\n\n\nextra lines")
        assert "   " not in result
        assert "\n\n\n" not in result

    def test_clean_text_preserves_newlines(self):
        result = self.clean("line1\nline2")
        assert "line1" in result
        assert "line2" in result

    def test_clean_text_empty(self):
        result = self.clean("")
        assert result == ""

    def test_extension_fallback_pdf(self):
        """Should use extension when mime type is generic"""
        from app.core.exceptions import ParseError
        # octet-stream with .pdf extension should attempt PDF parsing
        try:
            self.extract(b"not a real pdf", "application/octet-stream", "resume.pdf")
        except ParseError:
            pass  # Expected — content isn't real PDF
        except Exception as e:
            pytest.fail(f"Wrong exception type: {type(e).__name__}: {e}")


# ── Test: Security ────────────────────────────────────────────────────────────
class TestSecurity:
    def test_create_and_decode_token(self):
        from app.core.security import create_access_token, decode_token
        token = create_access_token({"sub": "user-123", "email": "test@test.com"})
        assert isinstance(token, str)
        assert len(token) > 20

        payload = decode_token(token)
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@test.com"

    def test_invalid_token_raises(self):
        from app.core.security import decode_token
        from app.core.exceptions import AuthError
        with pytest.raises(AuthError):
            decode_token("this.is.not.valid")

    def test_tampered_token_raises(self):
        from app.core.security import create_access_token, decode_token
        from app.core.exceptions import AuthError
        token = create_access_token({"sub": "user-123"})
        tampered = token[:-10] + "AAAAAAAAAA"
        with pytest.raises(AuthError):
            decode_token(tampered)


# ── Test: Config ──────────────────────────────────────────────────────────────
class TestConfig:
    def test_settings_load(self):
        from app.core.config import settings
        assert isinstance(settings.APP_ENV, str)
        assert isinstance(settings.MAX_FILE_SIZE_MB, int)
        assert settings.MAX_FILE_SIZE_MB > 0

    def test_allowed_origins_parsed(self):
        from app.core.config import Settings
        s = Settings(
            SECRET_KEY="test-32-char-key-aaaaaaaaaaaaaaa",
            ALLOWED_ORIGINS="http://localhost:3000,https://app.vercel.app",
            DATABASE_URL="postgresql://test",
            SUPABASE_URL="https://test.supabase.co",
            SUPABASE_SERVICE_KEY="test",
        )
        assert isinstance(s.allowed_origins_list, list)
        assert len(s.allowed_origins_list) == 2
        assert "http://localhost:3000" in s.allowed_origins_list


# ── Test: Exceptions ──────────────────────────────────────────────────────────
class TestExceptions:
    def test_file_too_large_has_max_mb(self):
        from app.core.exceptions import FileTooLarge
        e = FileTooLarge(max_mb=10)
        assert e.max_mb == 10
        assert e.http_status == 413
        assert "10" in e.message

    def test_rate_limit_has_retry_after(self):
        from app.core.exceptions import RateLimitExceeded
        e = RateLimitExceeded(retry_after=45)
        assert e.retry_after == 45
        assert e.http_status == 429

    def test_unsupported_file_type_stores_type(self):
        from app.core.exceptions import UnsupportedFileType
        e = UnsupportedFileType("image/png")
        assert e.file_type == "image/png"
        assert e.http_status == 415
