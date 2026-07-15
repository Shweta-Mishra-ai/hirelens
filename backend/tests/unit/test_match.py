"""
HireLens — JD Match (Feature 2) Unit Tests
Run: cd backend && python -m pytest tests/unit/test_match.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestMergeJdMatch:
    def setup_method(self):
        from app.services.ai.engine import AnalysisEngine
        self.engine = AnalysisEngine()

    def test_normal_values_pass_through(self):
        raw = {
            "match_percent": 82,
            "matching_skills": ["Python", "FastAPI"],
            "missing_skills": ["Kubernetes"],
            "verdict": "strong_fit",
            "rationale": "Strong overlap on backend stack.",
        }
        out = self.engine._merge_jd_match(raw)
        assert out["match_percent"] == 82
        assert out["verdict"] == "strong_fit"
        assert out["matching_skills"] == ["Python", "FastAPI"]

    def test_clamps_out_of_range_score(self):
        assert self.engine._merge_jd_match({"match_percent": 150})["match_percent"] == 100
        assert self.engine._merge_jd_match({"match_percent": -20})["match_percent"] == 0

    def test_handles_missing_percent(self):
        out = self.engine._merge_jd_match({})
        assert out["match_percent"] == 0
        assert out["verdict"] == "weak_fit"

    def test_derives_verdict_from_score_when_invalid(self):
        assert self.engine._merge_jd_match({"match_percent": 90, "verdict": "bogus"})["verdict"] == "strong_fit"
        assert self.engine._merge_jd_match({"match_percent": 60, "verdict": "bogus"})["verdict"] == "partial_fit"
        assert self.engine._merge_jd_match({"match_percent": 10, "verdict": "bogus"})["verdict"] == "weak_fit"

    def test_non_numeric_percent_defaults_to_zero(self):
        out = self.engine._merge_jd_match({"match_percent": "not-a-number"})
        assert out["match_percent"] == 0

    def test_caps_skill_list_length(self):
        raw = {"match_percent": 50, "matching_skills": [f"skill{i}" for i in range(40)]}
        out = self.engine._merge_jd_match(raw)
        assert len(out["matching_skills"]) <= 25


class TestJdInputResolution:
    def setup_method(self):
        import asyncio
        self.asyncio = asyncio

    def test_rejects_when_neither_text_nor_file(self):
        from app.api.v1.endpoints.match import _resolve_jd_text
        from app.core.exceptions import InvalidJobDescription
        with self._expect(InvalidJobDescription):
            self.asyncio.run(_resolve_jd_text(None, None))

    def test_rejects_too_short_text(self):
        from app.api.v1.endpoints.match import _resolve_jd_text
        from app.core.exceptions import InvalidJobDescription
        with self._expect(InvalidJobDescription):
            self.asyncio.run(_resolve_jd_text("too short", None))

    def test_accepts_valid_text(self):
        from app.api.v1.endpoints.match import _resolve_jd_text
        text = "We are hiring a Senior Backend Engineer with 5+ years of Python and FastAPI experience."
        result = self.asyncio.run(_resolve_jd_text(text, None))
        assert result == text

    class _expect:
        def __init__(self, exc_type):
            self.exc_type = exc_type

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            assert exc_type is not None and issubclass(exc_type, self.exc_type), \
                f"expected {self.exc_type}, got {exc_type}"
            return True


class TestMatchRanking:
    def setup_method(self):
        from app.api.v1.endpoints import analysis as analysis_mod
        from app.api.v1.endpoints import match as match_mod
        analysis_mod._jobs.clear()
        self.jobs = analysis_mod._jobs
        self.match = match_mod

        self.jobs["job-a"] = {
            "id": "job-a", "status": "complete", "stage": "complete", "progress": 100,
            "file_name": "a.pdf", "report_id": "rep-a", "error": None,
        }
        self.jobs["report_rep-a"] = {
            "candidate": {"name": "Dev A"}, "file_name": "a.pdf",
            "credibility": {"overall": 80, "recommendation": "recommended"},
            "jd_match": {"match_percent": 88, "matching_skills": ["Python"], "missing_skills": [], "verdict": "strong_fit"},
        }
        self.jobs["job-b"] = {
            "id": "job-b", "status": "complete", "stage": "complete", "progress": 100,
            "file_name": "b.pdf", "report_id": "rep-b", "error": None,
        }
        self.jobs["report_rep-b"] = {
            "candidate": {"name": "Dev B"}, "file_name": "b.pdf",
            "credibility": {"overall": 60, "recommendation": "manual_review"},
            "jd_match": {"match_percent": 40, "matching_skills": [], "missing_skills": ["Kubernetes"], "verdict": "weak_fit"},
        }

        self.batch = {"id": "batch-jd", "user_id": "u1", "job_ids": ["job-a", "job-b"], "total": 2}

    def test_ranks_by_match_percent_not_credibility_score(self):
        result = self.match._build_match_status(self.batch, db=None)
        assert [r["candidate_name"] for r in result["ranking"]] == ["Dev A", "Dev B"]

    def test_best_fit_flag_on_rank_one_only(self):
        result = self.match._build_match_status(self.batch, db=None)
        assert result["ranking"][0]["is_best_fit"] is True
        assert result["ranking"][1]["is_best_fit"] is False

    def test_missing_skills_present_for_weak_fit(self):
        result = self.match._build_match_status(self.batch, db=None)
        dev_b = next(r for r in result["ranking"] if r["candidate_name"] == "Dev B")
        assert "Kubernetes" in dev_b["missing_skills"]
