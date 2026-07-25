"""
HireLens — Recommendation Adjustment (verification feeds back into the
headline recommendation) Unit Tests
Run: cd backend && python -m pytest tests/unit/test_recommendation_adjustment.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.api.v1.endpoints.verify import _apply_verification_to_recommendation


def _report(recommendation):
    return {"credibility": {"overall": 75, "recommendation": recommendation}}


class TestDowngradeLogic:
    def test_downgrades_recommended_to_manual_review_on_low_confidence(self):
        report = _report("recommended")
        trust = {"verdict": "low_confidence", "evidence_available": True}
        result = _apply_verification_to_recommendation(report, trust)
        assert result == {"recommendation": "manual_review"}
        assert report["credibility"]["recommendation"] == "manual_review"

    def test_downgrades_manual_review_to_high_risk_on_low_confidence(self):
        report = _report("manual_review")
        trust = {"verdict": "low_confidence", "evidence_available": True}
        result = _apply_verification_to_recommendation(report, trust)
        assert result == {"recommendation": "high_risk"}

    def test_already_high_risk_stays_high_risk_no_update_needed(self):
        report = _report("high_risk")
        trust = {"verdict": "low_confidence", "evidence_available": True}
        result = _apply_verification_to_recommendation(report, trust)
        assert result is None
        assert report["credibility"]["recommendation"] == "high_risk"

    def test_preserves_original_ai_recommendation_for_transparency(self):
        report = _report("recommended")
        trust = {"verdict": "low_confidence", "evidence_available": True}
        _apply_verification_to_recommendation(report, trust)
        assert report["credibility"]["ai_recommendation"] == "recommended"
        assert report["credibility"]["recommendation_adjusted_by_verification"] is True
        assert "reason" not in report["credibility"] or report["credibility"].get("recommendation_adjustment_reason")

    def test_does_not_downgrade_twice_overwriting_original_ai_recommendation(self):
        """If verification is re-run and downgrades again, the ORIGINAL AI
        call should still be the preserved ai_recommendation, not the
        already-downgraded value from a previous run."""
        report = _report("recommended")
        trust = {"verdict": "low_confidence", "evidence_available": True}
        _apply_verification_to_recommendation(report, trust)  # recommended -> manual_review
        _apply_verification_to_recommendation(report, trust)  # manual_review -> high_risk
        assert report["credibility"]["ai_recommendation"] == "recommended"
        assert report["credibility"]["recommendation"] == "high_risk"


class TestNoDowngradeWhenNotWarranted:
    def test_no_change_on_high_confidence(self):
        report = _report("recommended")
        trust = {"verdict": "high_confidence", "evidence_available": True}
        result = _apply_verification_to_recommendation(report, trust)
        assert result is None
        assert report["credibility"]["recommendation"] == "recommended"

    def test_no_change_on_moderate_confidence(self):
        report = _report("recommended")
        trust = {"verdict": "moderate_confidence", "evidence_available": True}
        result = _apply_verification_to_recommendation(report, trust)
        assert result is None

    def test_no_change_when_no_evidence_available(self):
        """Low-confidence verdict with no actual evidence (e.g. GitHub
        username just wasn't provided) must NOT downgrade — that would be
        punishing candidates for missing optional data, not for red flags."""
        report = _report("recommended")
        trust = {"verdict": "low_confidence", "evidence_available": False}
        result = _apply_verification_to_recommendation(report, trust)
        assert result is None
        assert report["credibility"]["recommendation"] == "recommended"

    def test_never_auto_upgrades(self):
        """High-confidence verification must never push a high_risk AI
        verdict up to recommended — verification doesn't address whatever
        made the AI flag it in the first place."""
        report = _report("high_risk")
        trust = {"verdict": "high_confidence", "evidence_available": True}
        result = _apply_verification_to_recommendation(report, trust)
        assert result is None
        assert report["credibility"]["recommendation"] == "high_risk"

    def test_unknown_recommendation_value_handled_safely(self):
        report = {"credibility": {"recommendation": "some_unexpected_value"}}
        trust = {"verdict": "low_confidence", "evidence_available": True}
        result = _apply_verification_to_recommendation(report, trust)
        assert result is None  # doesn't crash, doesn't guess
