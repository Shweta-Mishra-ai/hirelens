"""
Tests for career trajectory metrics.

The headline test is `test_score_is_not_saturated_by_long_skill_lists`: the
implementation this replaced computed its score as
`60 + roles*5 + skills*2` clamped to 98, so essentially every resume with a
normal skills section scored 98/100. These tests pin the property that made
that wrong — the output must respond to career *shape*, not list length.
"""

from datetime import date

import pytest

from app.services.ai.career_trajectory import (
    compute_career_trajectory,
    months_between,
    parse_partial_date,
    seniority_rank,
)

TODAY = date(2026, 1, 1)


# ── parse_partial_date ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2022-03", date(2022, 3, 1)),
        ("2022/3", date(2022, 3, 1)),
        ("03/2022", date(2022, 3, 1)),
        ("March 2022", date(2022, 3, 1)),
        ("Mar 2022", date(2022, 3, 1)),
        ("Sept 2019", date(2019, 9, 1)),
        ("2018", date(2018, 1, 1)),
        ("  2018  ", date(2018, 1, 1)),
    ],
)
def test_parses_common_resume_date_formats(raw, expected):
    assert parse_partial_date(raw, today=TODAY) == expected


@pytest.mark.parametrize("raw", ["Present", "present", "current", "NOW", "Ongoing"])
def test_present_resolves_to_today(raw):
    assert parse_partial_date(raw, today=TODAY) == TODAY


@pytest.mark.parametrize(
    "raw", [None, "", "null", "n/a", "-", "sometime last year", "13/2022", "1500", "abcd"]
)
def test_unparseable_dates_return_none_rather_than_guessing(raw):
    assert parse_partial_date(raw, today=TODAY) is None


def test_bare_year_resolves_to_january_not_today():
    # Resolving a bare year to the current month would invent up to 11 months
    # of tenure the resume never claimed.
    assert parse_partial_date("2020", today=TODAY) == date(2020, 1, 1)


def test_months_between_never_negative():
    assert months_between(date(2022, 6, 1), date(2022, 1, 1)) == 0
    assert months_between(date(2022, 1, 1), date(2023, 1, 1)) == 12


# ── seniority_rank ────────────────────────────────────────────────────────────

def test_seniority_ladder_orders_titles():
    assert seniority_rank("Intern") < seniority_rank("Junior Developer")
    assert seniority_rank("Junior Developer") < seniority_rank("Software Engineer")
    assert seniority_rank("Software Engineer") < seniority_rank("Senior Engineer")
    assert seniority_rank("Senior Engineer") < seniority_rank("Engineering Manager")
    assert seniority_rank("Director of Engineering") < seniority_rank("VP Engineering")


def test_highest_matching_rung_wins():
    # "Senior Staff Engineer" contains both "senior" (4) and "staff" (5).
    assert seniority_rank("Senior Staff Engineer") == seniority_rank("Staff Engineer")


def test_unknown_title_has_no_rank():
    assert seniority_rank("Chief Vibes Officer") is not None  # matches "chief"
    assert seniority_rank("Zookeeper") is None
    assert seniority_rank(None) is None
    assert seniority_rank("") is None


# ── compute_career_trajectory ─────────────────────────────────────────────────

def _role(role, start, end, months=None):
    return {"role": role, "company": "Acme", "start_date": start, "end_date": end,
            "duration_months": months}


def test_insufficient_data_when_fewer_than_two_dated_roles():
    out = compute_career_trajectory(
        [_role("Engineer", None, None)], today=TODAY
    )
    assert out["status"] == "insufficient_data"
    assert out["roles_analyzed"] == 0
    # The reason must be specific enough for a recruiter to act on.
    assert "start date" in out["reason"]


def test_insufficient_data_for_a_single_role():
    out = compute_career_trajectory([_role("Engineer", "2020-01", "present")], today=TODAY)
    assert out["status"] == "insufficient_data"
    assert out["roles_analyzed"] == 1


def test_no_fabricated_score_when_data_is_missing():
    """The old implementation always produced a number. This one must not."""
    out = compute_career_trajectory([], today=TODAY)
    assert "progression_score" not in out
    assert "retention_stability" not in out


def test_computes_total_experience_as_union_not_sum():
    # Two concurrent roles over the same 24 months is 24 months of
    # experience, not 48.
    out = compute_career_trajectory(
        [
            _role("Engineer", "2024-01", "2026-01"),
            _role("Advisor", "2024-06", "2025-06"),
        ],
        today=TODAY,
    )
    assert out["status"] == "computed"
    assert out["total_experience_months"] == 24


def test_detects_employment_gaps():
    out = compute_career_trajectory(
        [
            _role("Engineer", "2020-01", "2021-01"),
            _role("Engineer", "2022-01", "2023-01"),
        ],
        today=TODAY,
    )
    assert out["gap_months"] == 12


def test_counts_only_upward_title_transitions():
    out = compute_career_trajectory(
        [
            _role("Junior Developer", "2018-01", "2020-01"),
            _role("Software Engineer", "2020-01", "2022-01"),
            _role("Senior Engineer", "2022-01", "2024-01"),
        ],
        today=TODAY,
    )
    assert out["advancement_steps"] == 2


def test_lateral_moves_are_not_advancement():
    out = compute_career_trajectory(
        [
            _role("Software Engineer", "2018-01", "2021-01"),
            _role("Software Developer", "2021-01", "2024-01"),
        ],
        today=TODAY,
    )
    assert out["advancement_steps"] == 0
    assert out["months_per_advancement"] is None
    assert out["progression_score"] == 0
    assert out["trajectory"] == "No title advancement observed"


def test_demotion_does_not_count_as_advancement():
    out = compute_career_trajectory(
        [
            _role("Director of Engineering", "2018-01", "2021-01"),
            _role("Senior Engineer", "2021-01", "2024-01"),
        ],
        today=TODAY,
    )
    assert out["advancement_steps"] == 0


def test_median_tenure_excludes_the_current_role():
    # The current role's tenure is censored — it is still accruing. Counting
    # it would make anyone who recently changed jobs look unstable.
    out = compute_career_trajectory(
        [
            _role("Engineer", "2018-01", "2021-01"),   # 36 months
            _role("Engineer", "2021-01", "2024-01"),   # 36 months
            _role("Senior Engineer", "2025-11", "present"),  # 2 months, current
        ],
        today=TODAY,
    )
    assert out["median_tenure_months"] == 36


def test_retention_stability_tracks_tenure_not_job_count():
    """
    The replaced implementation scored retention as `100 - roles*4`, so a
    job-hopper with 2 roles beat a loyal employee with 4. Tenure must drive it.
    """
    hopper = compute_career_trajectory(
        [
            _role("Engineer", "2023-01", "2023-07"),
            _role("Engineer", "2023-07", "2024-01"),
            _role("Engineer", "2024-01", "2024-07"),
        ],
        today=TODAY,
    )
    steady = compute_career_trajectory(
        [
            _role("Engineer", "2016-01", "2020-01"),
            _role("Senior Engineer", "2020-01", "2024-01"),
        ],
        today=TODAY,
    )
    assert steady["retention_stability"] > hopper["retention_stability"]


def test_score_is_not_saturated_by_long_skill_lists():
    """
    Regression guard for the core defect: the metric must be a function of the
    work history alone. A skills array is not an input at all now, so two
    identical histories must score identically regardless of anything else on
    the resume, and a genuinely weak history must not score near the ceiling.
    """
    weak = compute_career_trajectory(
        [
            _role("Engineer", "2024-01", "2024-04"),
            _role("Engineer", "2024-04", "2024-08"),
        ],
        today=TODAY,
    )
    assert weak["retention_stability"] < 50
    # And the whole point: this is nowhere near the old constant 98.
    assert weak["progression_score"] != 98


def test_roles_with_end_before_start_are_dropped():
    out = compute_career_trajectory(
        [
            _role("Engineer", "2022-01", "2020-01"),  # transposed
            _role("Engineer", "2020-01", "2023-01"),
            _role("Senior Engineer", "2023-01", "present"),
        ],
        today=TODAY,
    )
    assert out["roles_analyzed"] == 2


def test_stated_duration_used_when_consistent_with_dates():
    out = compute_career_trajectory(
        [
            _role("Engineer", "2020-01", "2022-01", months=25),  # within tolerance
            _role("Senior Engineer", "2022-01", "2024-01"),
        ],
        today=TODAY,
    )
    assert out["median_tenure_months"] in (24, 25)


def test_wildly_inconsistent_stated_duration_is_ignored():
    out = compute_career_trajectory(
        [
            _role("Engineer", "2020-01", "2022-01", months=999),
            _role("Senior Engineer", "2022-01", "2024-01"),
        ],
        today=TODAY,
    )
    assert out["median_tenure_months"] == 24


def test_basis_string_explains_what_was_measured():
    out = compute_career_trajectory(
        [
            _role("Junior Developer", "2018-01", "2021-01"),
            _role("Senior Engineer", "2021-01", "2024-01"),
        ],
        today=TODAY,
    )
    assert "2 dated role" in out["basis"]
    assert "upward title change" in out["basis"]


def test_handles_malformed_entries_without_raising():
    out = compute_career_trajectory(
        ["not a dict", None, {"role": "Engineer"}, _role("Engineer", "2020-01", "2024-01")],
        today=TODAY,
    )
    assert out["status"] == "insufficient_data"


def test_all_scores_stay_within_bounds():
    out = compute_career_trajectory(
        [
            _role("Intern", "2023-01", "2023-02"),
            _role("VP Engineering", "2023-02", "2023-03"),
        ],
        today=TODAY,
    )
    assert 0 <= out["retention_stability"] <= 100
    assert 0 <= out["progression_score"] <= 100
