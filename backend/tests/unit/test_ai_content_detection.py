"""
HireLens — AI Content Detection Feature Unit Tests
Run: cd backend && python -m pytest tests/unit/test_ai_content_detection.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.ai.engine import AnalysisEngine


class TestMergeAIContentAnalysis:
    def setup_method(self):
        self.engine = AnalysisEngine()

    def test_normal_values_pass_through(self):
        raw = {
            "likelihood": "high",
            "indicators": ["Every bullet uses 'leveraged synergies'", "Suspiciously uniform structure"],
            "human_indicators": [],
            "note": "Strong AI-writing pattern signals.",
        }
        out = self.engine._merge_ai_content_analysis(raw)
        assert out["likelihood"] == "high"
        assert len(out["indicators"]) == 2
        assert out["note"] == "Strong AI-writing pattern signals."

    def test_missing_input_defaults_to_low_not_high(self):
        # Conservative default — never accuse a candidate without an actual signal
        out = self.engine._merge_ai_content_analysis(None)
        assert out["likelihood"] == "low"
        assert out["indicators"] == []

    def test_invalid_likelihood_value_defaults_to_low(self):
        out = self.engine._merge_ai_content_analysis({"likelihood": "definitely-fake-nonsense"})
        assert out["likelihood"] == "low"

    def test_caps_indicator_list_length(self):
        raw = {"likelihood": "medium", "indicators": [f"signal {i}" for i in range(20)]}
        out = self.engine._merge_ai_content_analysis(raw)
        assert len(out["indicators"]) <= 8

    def test_non_string_indicators_coerced_safely(self):
        raw = {"likelihood": "low", "indicators": [123, None, "real one"]}
        out = self.engine._merge_ai_content_analysis(raw)
        assert all(isinstance(x, str) for x in out["indicators"])

    def test_empty_dict_input(self):
        out = self.engine._merge_ai_content_analysis({})
        assert out["likelihood"] == "low"
        assert out["indicators"] == []
        assert out["human_indicators"] == []
        assert out["note"] == ""


class TestSubScoreWeighting:
    def setup_method(self):
        self.engine = AnalysisEngine()

    def test_content_authenticity_included_in_overall_when_missing(self):
        extracted = {"candidate": {}, "skills": {}}
        analysis = {
            "credibility": {
                "overall": 0,  # force weighted computation
                "sub_scores": {
                    "timeline": 80, "skills_consistency": 80, "education": 80,
                    "project_authenticity": 80, "resume_quality": 80,
                    "content_authenticity": 20,  # heavily AI-flagged
                },
            },
        }
        result = self.engine._merge(extracted, analysis)
        # With content_authenticity dragged down to 20 and a 0.15 weight,
        # overall should be meaningfully below 80 (proving the new dimension
        # actually influences the score, not just decoration)
        assert result["credibility"]["overall"] < 80
        assert result["credibility"]["sub_scores"]["content_authenticity"] == 20

    def test_full_merge_includes_ai_content_analysis_field(self):
        extracted = {"candidate": {"name": "Test Person"}, "skills": {}}
        analysis = {
            "credibility": {"overall": 75, "sub_scores": {}},
            "ai_content_analysis": {
                "likelihood": "medium",
                "indicators": ["generic buzzwords"],
                "human_indicators": ["specific project detail"],
                "note": "Mixed signals.",
            },
        }
        result = self.engine._merge(extracted, analysis)
        assert "ai_content_analysis" in result
        assert result["ai_content_analysis"]["likelihood"] == "medium"

    def test_missing_ai_content_analysis_does_not_crash_merge(self):
        extracted = {"candidate": {}, "skills": {}}
        analysis = {"credibility": {"overall": 60, "sub_scores": {}}}
        result = self.engine._merge(extracted, analysis)
        assert result["ai_content_analysis"]["likelihood"] == "low"
