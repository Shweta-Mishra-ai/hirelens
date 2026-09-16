"""
Shape guards for stored report blobs.

The bug that motivated this file: `GET /reports` walks every report the
user owns to build the list, reaching into each blob with
`blob.get("candidate") or {}`. That handles a missing field but not one of
the wrong type, so a single blob whose `candidate` was a string raised
AttributeError — and because the list is built in one pass, that one
report returned 500 for the whole dashboard. The recruiter saw no
candidates and no error, because an unhandled exception used to skip the
CORS middleware and the browser would not let the app read the response.
"""

import pytest

from app.core.shapes import (
    as_dict,
    as_list,
    as_score,
    as_str,
    normalize_report,
    report_summary_row,
)


class TestPrimitives:
    @pytest.mark.parametrize("value", [None, "text", 5, [], (), object()])
    def test_a_non_mapping_becomes_an_empty_mapping(self, value):
        assert as_dict(value) == {}

    def test_a_mapping_is_returned_as_is(self):
        assert as_dict({"a": 1}) == {"a": 1}

    @pytest.mark.parametrize("value", [None, "abc", 5, {}, object()])
    def test_a_non_list_becomes_an_empty_list(self, value):
        assert as_list(value) == []

    def test_a_string_is_not_exploded_into_characters(self):
        """list("abc") would be three entries — three flags nobody wrote."""
        assert as_list("abc") == []

    def test_a_list_is_returned_as_is(self):
        assert as_list([1, 2]) == [1, 2]

    @pytest.mark.parametrize(
        "value,expected",
        [
            (74, 74), (74.6, 74), ("74", 74), (" 82 ", 82),
            (-5, 0), (250, 100), ("seventy", 0), (None, 0),
            (True, 0), (False, 0), ([], 0), ({}, 0),
        ],
    )
    def test_scores_are_clamped_whole_numbers(self, value, expected):
        assert as_score(value) == expected

    def test_a_score_can_take_its_own_default(self):
        assert as_score("nonsense", default=50) == 50

    @pytest.mark.parametrize("value", [None, 5, [], {}])
    def test_a_non_string_becomes_the_default(self, value):
        assert as_str(value) == ""
        assert as_str(value, "fallback") == "fallback"


class TestNormalizeReport:
    def test_a_well_formed_report_is_unchanged(self):
        report = {
            "candidate": {"name": "Anita Rao"},
            "skills": {"all_claimed": ["python"]},
            "experience": [{"company": "Acme"}],
            "flags": [{"severity": "medium"}],
            "credibility": {"overall": 74, "recommendation": "manual_review"},
            "summary": "Solid.",
        }
        assert normalize_report(report) == report

    def test_wrongly_typed_objects_become_empty_objects(self):
        out = normalize_report({
            "candidate": "not a dict",
            "skills": ["not", "a", "dict"],
            "credibility": 5,
            "career_trajectory": [],
        })
        assert out["candidate"] == {}
        assert out["skills"] == {}
        assert out["credibility"] == {}
        assert out["career_trajectory"] == {}

    def test_wrongly_typed_collections_become_empty_collections(self):
        out = normalize_report({
            "experience": "not a list",
            "flags": "critical",
            "education": None,
            "interview_questions": {"not": "a list"},
        })
        assert out["experience"] == []
        assert out["flags"] == []
        assert out["education"] == []
        assert out["interview_questions"] == []

    def test_a_non_numeric_score_does_not_survive_into_the_report(self):
        out = normalize_report({"credibility": {"overall": "seventy", "recommendation": 123}})
        assert out["credibility"]["overall"] == 0
        assert out["credibility"]["recommendation"] == "manual_review"

    def test_absent_fields_are_not_invented(self):
        assert normalize_report({"summary": "x"}) == {"summary": "x"}

    def test_unknown_keys_are_left_alone(self):
        out = normalize_report({"candidate": "bad", "some_future_field": {"a": 1}})
        assert out["some_future_field"] == {"a": 1}

    def test_the_original_is_not_mutated(self):
        original = {"candidate": "not a dict"}
        normalize_report(original)
        assert original["candidate"] == "not a dict"

    @pytest.mark.parametrize("value", [None, "text", 5, [], True])
    def test_a_blob_that_is_not_a_report_at_all_becomes_an_empty_one(self, value):
        assert normalize_report(value) == {}


class TestSummaryRow:
    def test_a_normal_report_summarises(self):
        row = report_summary_row("r1", {
            "file_name": "anita.pdf",
            "candidate": {"name": "Anita Rao"},
            "credibility": {"overall": 91, "recommendation": "recommended"},
        })
        assert row == {
            "id": "r1",
            "file_name": "anita.pdf",
            "candidate_name": "Anita Rao",
            "overall_score": 91,
            "recommendation": "recommended",
        }

    def test_a_hostile_report_still_produces_a_row(self):
        row = report_summary_row("r1", {
            "file_name": None,
            "candidate": "not a dict",
            "credibility": {"overall": "seventy", "recommendation": []},
        }, fallback_file_name="legacy.pdf")
        assert row["candidate_name"] == "Unknown"
        assert row["overall_score"] == 0
        assert row["recommendation"] == "manual_review"
        assert row["file_name"] == "legacy.pdf"

    def test_a_blob_that_is_not_a_dict_still_produces_a_row(self):
        row = report_summary_row("r1", "not a report")
        assert row["id"] == "r1"
        assert row["candidate_name"] == "Unknown"
        assert row["overall_score"] == 0
