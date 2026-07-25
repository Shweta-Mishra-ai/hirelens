"""
HireLens — Trust Assessment Unit Tests
Run: cd backend && python -m pytest tests/unit/test_trust_assessment.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.verify.trust_assessment import compute_trust_assessment


class TestTrustAssessment:
    def test_no_verification_data_is_insufficient_evidence(self):
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "low"},
            verification=None,
            overall_score=75,
        )
        assert result["verdict"] == "insufficient_evidence"
        assert result["evidence_available"] is False

    def test_github_verified_plus_low_ai_risk_is_high_confidence(self):
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "low"},
            verification={"github": {"status": "verified", "verified_skills": ["Python", "React", "Docker"]}},
            overall_score=85,
        )
        assert result["verdict"] == "high_confidence"
        assert result["score"] > 25
        assert result["evidence_available"] is True

    def test_github_not_found_is_a_strong_negative_signal(self):
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "low"},
            verification={"github": {"status": "not_found"}},
            overall_score=70,
        )
        assert result["score"] < 0
        assert any("does not correspond to a real account" in r for r in result["reasoning"])

    def test_high_ai_likelihood_alone_does_not_crater_score_without_other_evidence(self):
        """AI-writing-style signal is deliberately weak on its own — this
        guards against the exact failure mode of over-trusting stylistic
        analysis that modern AI models can trivially evade."""
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "high"},
            verification=None,
            overall_score=70,
        )
        assert result["verdict"] == "insufficient_evidence"  # no real-world evidence either way

    def test_education_registry_gap_is_only_a_weak_penalty(self):
        """Registry coverage gaps are common and must never be damning on their own."""
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "low"},
            verification={"education": [{"institution": "Small Regional College", "status": "not_found"}]},
            overall_score=75,
        )
        assert result["score"] >= -10  # small penalty, not a verdict-defining one

    def test_combined_strong_positive_signals_stack(self):
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "low"},
            verification={
                "github": {"status": "verified", "verified_skills": ["Python", "Go"]},
                "education": [{"institution": "MIT", "status": "verified"}],
            },
            overall_score=90,
        )
        assert result["verdict"] == "high_confidence"

    def test_combined_strong_negative_signals_stack(self):
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "high"},
            verification={"github": {"status": "not_found"}},
            overall_score=40,
        )
        assert result["verdict"] == "low_confidence"
        assert result["score"] < -10

    def test_reasoning_is_always_populated_and_traceable(self):
        """Every verdict must be explainable — this is the whole point of
        being rule-based instead of another LLM call."""
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "medium"},
            verification={"github": {"status": "partial"}},
            overall_score=60,
        )
        assert len(result["reasoning"]) >= 2
        assert all(isinstance(r, str) and len(r) > 0 for r in result["reasoning"])

    def test_score_is_always_clamped_to_valid_range(self):
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "high"},
            verification={
                "github": {"status": "not_found"},
                "education": [{"status": "not_found"}, {"status": "not_found"}],
            },
            overall_score=10,
        )
        assert -100 <= result["score"] <= 100

    def test_missing_ai_content_analysis_does_not_crash(self):
        result = compute_trust_assessment(
            ai_content_analysis=None,
            verification={"github": {"status": "verified", "verified_skills": []}},
            overall_score=70,
        )
        assert result["verdict"] in ("high_confidence", "moderate_confidence", "low_confidence", "insufficient_evidence")

    def test_no_username_github_does_not_count_as_negative_evidence(self):
        """Not providing a GitHub username at all is neutral, not suspicious."""
        result = compute_trust_assessment(
            ai_content_analysis={"likelihood": "low"},
            verification={"github": {"status": "no_username"}},
            overall_score=70,
        )
        assert result["verdict"] == "insufficient_evidence"
