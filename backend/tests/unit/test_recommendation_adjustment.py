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

    def test_a_rerun_on_the_same_evidence_does_not_downgrade_again(self):
        """Verification is documented as safe to re-run, and it is a button
        the recruiter can click twice. It used to downgrade relative to the
        CURRENT verdict, so a second click took the candidate one level
        further down — recommended → manual_review → high_risk — without a
        single new piece of evidence. The drop is now measured from the
        AI's original read, so a re-run lands where the first run did."""
        report = _report("recommended")
        trust = {"verdict": "low_confidence", "evidence_available": True}
        first = _apply_verification_to_recommendation(report, trust)
        second = _apply_verification_to_recommendation(report, trust)
        assert first == {"recommendation": "manual_review"}
        assert second is None
        assert report["credibility"]["ai_recommendation"] == "recommended"
        assert report["credibility"]["recommendation"] == "manual_review"

    def test_new_evidence_can_still_downgrade_a_report_the_ai_already_doubted(self):
        """Anchoring to the AI's read must not make the rule inert: a
        candidate the AI already sent to manual review still drops to
        high_risk when verification contradicts them."""
        report = _report("manual_review")
        trust = {"verdict": "low_confidence", "evidence_available": True}
        assert _apply_verification_to_recommendation(report, trust) == {"recommendation": "high_risk"}
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
