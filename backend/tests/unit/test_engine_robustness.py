"""
Engine merge robustness against malformed LLM output.

`_merge` promised in its docstring that "all field accesses are safe (handles
missing/null from LLM)", but coerced scores with a bare `int(...)`. A model
that answered "74%" or "high" instead of 74 raised ValueError and failed the
entire analysis — after the user had already waited through it. Sub-scores
were never range-checked either, so a negative value reached the UI and
rendered a progress bar with a negative width.

LLMs do return strings where numbers are expected. This is not a theoretical
input class.
"""

import pytest

from app.services.ai.engine import AnalysisEngine

engine = AnalysisEngine()

VALID_RECOMMENDATIONS = {"recommended", "manual_review", "high_risk"}
SUB_SCORE_KEYS = [
    "timeline",
    "skills_consistency",
    "education",
    "project_authenticity",
    "resume_quality",
    "content_authenticity",
]


def _assert_wellformed(report):
    cred = report["credibility"]
    assert isinstance(cred["overall"], int)
    assert 0 <= cred["overall"] <= 100
    assert cred["recommendation"] in VALID_RECOMMENDATIONS
    for key in SUB_SCORE_KEYS:
        value = cred["sub_scores"][key]
        assert isinstance(value, int), f"{key} is {type(value).__name__}"
        assert 0 <= value <= 100, f"{key} out of range: {value}"
    for key in ("experience", "education", "projects", "certifications",
                "flags", "positive_signals", "interview_questions", "timeline_gaps"):
        assert isinstance(report[key], list), f"{key} is not a list"


class TestScoreCoercion:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (74, 74),
            (74.6, 74),
            ("74", 74),
            ("74%", 74),
            (" 74 ", 74),
            ("74/100", 74),
            ("score: 74", 74),
        ],
    )
    def test_numeric_shapes_are_accepted(self, raw, expected):
        report = engine._merge({}, {"credibility": {"overall": raw}})
        assert report["credibility"]["overall"] == expected

    @pytest.mark.parametrize("raw", ["high", "abc", "", None, [], {}, True, False])
    def test_unusable_values_fall_back_instead_of_raising(self, raw):
        report = engine._merge({}, {"credibility": {"overall": raw}})
        _assert_wellformed(report)

    @pytest.mark.parametrize("raw,expected", [(-50, 0), (999, 100), ("-20", 0), ("1000", 100)])
    def test_out_of_range_scores_are_clamped(self, raw, expected):
        report = engine._merge({}, {"credibility": {"sub_scores": {"timeline": raw}}})
        assert report["credibility"]["sub_scores"]["timeline"] == expected

    def test_a_negative_subscore_never_reaches_the_ui(self):
        report = engine._merge(
            {},
            {"credibility": {"overall": 70, "sub_scores": {k: -99 for k in SUB_SCORE_KEYS}}},
        )
        _assert_wellformed(report)

    def test_booleans_are_not_treated_as_scores(self):
        # bool is an int subclass; True would otherwise score as 1.
        report = engine._merge({}, {"credibility": {"sub_scores": {"timeline": True}}})
        assert report["credibility"]["sub_scores"]["timeline"] == 70


class TestStructuralRobustness:
    @pytest.mark.parametrize(
        "extracted,analysis",
        [
            ({}, {}),
            ({"candidate": None, "skills": None, "experience": None}, {"credibility": None}),
            ({"experience": "not a list", "skills": ["not", "a", "dict"]},
             {"flags": "not a list", "credibility": {"overall": "abc", "sub_scores": "nope"}}),
            ({"skills": "a string"}, {"skills_verification": 42}),
            ({"experience": {"not": "a list"}}, {"interview_questions": "none"}),
            ({}, {"credibility": []}),
            ({"certifications": None}, {"positive_signals": {}}),
        ],
    )
    def test_merge_never_raises_on_malformed_output(self, extracted, analysis):
        _assert_wellformed(engine._merge(extracted, analysis))

    def test_very_large_payloads_are_handled(self):
        report = engine._merge(
            {"skills": {"all_claimed": ["x"] * 10_000}},
            {"flags": [{"severity": "high", "title": "t"}] * 2_000},
        )
        _assert_wellformed(report)

    def test_a_string_where_a_list_belongs_becomes_empty_not_characters(self):
        """list("abc") would silently produce ['a','b','c'] — three fake flags."""
        report = engine._merge({}, {"flags": "abc"})
        assert report["flags"] == []

    def test_career_trajectory_still_computed_from_valid_experience(self):
        report = engine._merge(
            {
                "experience": [
                    {"role": "Junior Developer", "start_date": "2018-01", "end_date": "2021-01"},
                    {"role": "Senior Engineer", "start_date": "2021-01", "end_date": "2024-01"},
                ]
            },
            {},
        )
        assert report["career_trajectory"]["status"] == "computed"

    def test_career_trajectory_survives_malformed_experience(self):
        report = engine._merge({"experience": "not a list"}, {})
        assert report["career_trajectory"]["status"] == "insufficient_data"
