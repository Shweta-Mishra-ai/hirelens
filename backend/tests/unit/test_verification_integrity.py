"""
HireLens — verification integrity tests
Run: cd backend && python -m pytest tests/unit/test_verification_integrity.py -v

This product's entire pitch is "evidence, not guesses". These tests defend
that claim rather than any particular feature:

1. A "verified" verdict must not be derivable from a channel an attacker can
   rewrite. The university registry lookup ran over plain HTTP, and its
   result becomes `status: "verified"` on a candidate's degree — anyone on
   the network path could forge a match for a fabricated institution, or
   blank a real one so the candidate's trust score dropped.

2. "We could not check" must never be reported as "we checked and found
   nothing". A network failure that reads as `not_found` turns an outage
   into an accusation against a real candidate.

3. Every point in the trust score must be explainable. compute_trust_assessment
   promises in its own docstring that each adjustment is recorded in
   `reasoning`; a silent one makes a verdict that nobody — recruiter or
   developer — can reconstruct.
"""

import pytest

from app.services.verify import education_verify
from app.services.verify.trust_assessment import compute_trust_assessment


class TestRegistryLookupIntegrity:
    def test_university_registry_is_queried_over_https(self):
        """A degree marked "verified" must not rest on a plaintext response."""
        assert education_verify.HIPOLABS_URL.startswith("https://")

    def test_there_is_no_http_downgrade_path(self):
        """A fallback to http on TLS failure would hand the property straight
        back, at exactly the moment interference is most likely."""
        import inspect

        src = inspect.getsource(education_verify)
        code = "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )
        assert "http://" not in code


class TestUnreachableIsNotDisproven:
    @pytest.mark.asyncio
    async def test_network_failure_reports_error_not_not_found(self, monkeypatch):
        """The distinction that protects a real candidate from an outage."""

        async def always_fails(client, query):
            return None

        monkeypatch.setattr(education_verify, "_search_once", always_fails)

        result = await education_verify.verify_education([{"institution": "Stanford University"}])

        assert result[0]["status"] == "error"
        assert result[0]["status"] != "not_found"

    @pytest.mark.asyncio
    async def test_a_genuine_empty_result_is_reported_as_not_found(self, monkeypatch):
        """...and the honest negative still has to work."""

        async def always_empty(client, query):
            return []

        monkeypatch.setattr(education_verify, "_search_once", always_empty)

        result = await education_verify.verify_education(
            [{"institution": "Totally Fictional University XYZ"}]
        )

        assert result[0]["status"] == "not_found"
        # ...and says plainly that this is not proof of anything.
        assert "does NOT necessarily mean" in result[0]["note"]

    @pytest.mark.asyncio
    async def test_a_missing_institution_name_is_skipped_not_failed(self, monkeypatch):
        async def unused(client, query):  # pragma: no cover - must not be called
            raise AssertionError("should not query the registry for a blank name")

        monkeypatch.setattr(education_verify, "_search_once", unused)

        result = await education_verify.verify_education([{"institution": "  "}])
        assert result[0]["status"] == "skipped"


class TestTrustScoreIsFullyExplainable:
    """Every adjustment must leave a trace. See the module docstring."""

    def _base_verification(self):
        return {"github": {"status": "no_username"}, "education": []}

    def test_high_credibility_bonus_is_explained(self):
        res = compute_trust_assessment({}, self._base_verification(), overall_score=90)
        assert any("90/100" in r for r in res["reasoning"])

    def test_low_credibility_penalty_is_explained(self):
        res = compute_trust_assessment({}, self._base_verification(), overall_score=30)
        assert any("30/100" in r for r in res["reasoning"])

    def test_two_candidates_with_different_scores_do_not_share_identical_reasoning(self):
        """The concrete symptom of the bug: same explanation, 16-point gap.

        A recruiter comparing two candidates side by side would have seen no
        difference in the stated reasons while the verdicts diverged.
        """
        v = self._base_verification()
        high = compute_trust_assessment({}, v, overall_score=90)
        low = compute_trust_assessment({}, v, overall_score=30)

        assert high["score"] - low["score"] == 16
        assert high["reasoning"] != low["reasoning"]

    def test_every_point_of_the_score_is_accounted_for_in_reasoning(self):
        """Sum the numbers written in the explanation and compare to the score.

        This is the real invariant: not "is there a line", but "do the lines
        add up to the number". A future signal added without a reasoning entry
        fails here.
        """
        import re

        cases = [
            ({"likelihood": "high"}, {"github": {"status": "not_found"}, "education": []}, 30),
            (
                {"likelihood": "low"},
                {
                    "github": {"status": "verified", "verified_skills": ["python", "go"]},
                    "education": [{"status": "verified"}],
                },
                85,
            ),
            ({"likelihood": "medium"}, {"github": {"status": "partial"}, "education": [{"status": "not_found"}]}, 60),
        ]

        for ai, verification, score in cases:
            res = compute_trust_assessment(ai, verification, overall_score=score)
            stated = 0
            for line in res["reasoning"]:
                # Matches "(+15)", "(−25)", "(-8, light weight ...)"
                m = re.search(r"\(([+−-])(\d+)", line)
                if m:
                    sign = -1 if m.group(1) in ("-", "−") else 1
                    stated += sign * int(m.group(2))
            assert stated == res["score"], (
                f"reasoning sums to {stated} but score is {res['score']}: {res['reasoning']}"
            )

    def test_unreachable_github_is_neither_credit_nor_penalty(self):
        """An outage must not read as a red flag against the candidate."""
        for status in ("error", "rate_limited", "no_username"):
            res = compute_trust_assessment(
                {}, {"github": {"status": status}, "education": []}, overall_score=60
            )
            assert res["evidence_available"] is False
            assert res["verdict"] == "insufficient_evidence"

    def test_no_evidence_never_yields_a_confident_verdict(self):
        """Even a perfect credibility score can't manufacture confidence."""
        res = compute_trust_assessment({}, {"github": {"status": "error"}, "education": []}, overall_score=100)
        assert res["verdict"] == "insufficient_evidence"
