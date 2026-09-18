"""
Tests for GitHub skill-evidence matching.

The implementation these cover replaced a bidirectional substring check:

    if skill_l == term_l or skill_l in term_l or term_l in skill_l:

A false "verified" is worse than reporting nothing, because it tells a
recruiter that a claim has been independently corroborated when it has not.
The substring rule produced them constantly — "Java" verified by a
JavaScript repo, "R" by Rust or React, "Go" by Google or Django, "C" by
almost anything.
"""

import pytest

from app.services.verify.github_verify import (
    _skill_matches_evidence,
    _normalize,
    _tokens,
    extract_username,
)


# ── The regressions that motivated the rewrite ────────────────────────────────

@pytest.mark.parametrize(
    "skill,evidence",
    [
        ("Java", {"javascript"}),          # the classic
        ("R", {"rust"}),
        ("R", {"react"}),
        ("R", {"terraform"}),
        ("Go", {"google"}),
        ("Go", {"django"}),
        ("Go", {"mongodb"}),
        ("C", {"css"}),
        ("C", {"c++"}),
        ("C", {"objective-c"}),
        ("AI", {"domain"}),
        ("ML", {"html"}),
        ("Ada", {"adapter"}),
        ("Rust", {"trustpilot"}),
        ("SQL", {"sqlalchemy-tutorial"}),
    ],
)
def test_substring_collisions_are_not_verified(skill, evidence):
    assert _skill_matches_evidence(skill, evidence) is False, (
        f"{skill!r} must not be verified by {evidence!r}"
    )


def test_java_is_not_verified_by_a_javascript_only_profile():
    evidence = {"javascript", "typescript", "html", "css", "react"}
    assert _skill_matches_evidence("Java", evidence) is False
    assert _skill_matches_evidence("JavaScript", evidence) is True


# ── Matches that must keep working ────────────────────────────────────────────

@pytest.mark.parametrize(
    "skill,evidence",
    [
        ("Python", {"python"}),
        ("python", {"Python"}),
        ("  Python  ", {"python"}),
        ("Go", {"go"}),
        ("Go", {"golang"}),
        ("Golang", {"go"}),
        ("R", {"r"}),
        ("C", {"c"}),
        ("Java", {"java"}),
    ],
)
def test_exact_and_family_matches_are_verified(skill, evidence):
    assert _skill_matches_evidence(skill, evidence) is True


@pytest.mark.parametrize(
    "skill,evidence",
    [
        # GitHub reports the language as "Dockerfile"; resumes say "Docker".
        ("Docker", {"dockerfile"}),
        ("Dockerfile", {"docker"}),
        ("C#", {"csharp"}),
        ("csharp", {"c#"}),
        (".NET", {"c#"}),
        ("Node.js", {"nodejs"}),
        ("nodejs", {"node.js"}),
        ("Postgres", {"plpgsql"}),
        ("PostgreSQL", {"postgres"}),
        ("K8s", {"kubernetes"}),
        ("Kubernetes", {"k8s"}),
        ("Bash", {"shell"}),
        ("Keras", {"tensorflow"}),
        ("SCSS", {"css"}),
    ],
)
def test_equivalence_families_work_in_both_directions(skill, evidence):
    assert _skill_matches_evidence(skill, evidence) is True


def test_family_membership_is_not_transitive_across_families():
    # Both are "languages that compile to JS", but they are distinct claims.
    assert _skill_matches_evidence("TypeScript", {"javascript"}) is False
    assert _skill_matches_evidence("Vue", {"react"}) is False


def test_whole_token_inside_a_multi_word_topic_counts():
    assert _skill_matches_evidence("Kubernetes", {"kubernetes operator sdk"}) is True
    assert _skill_matches_evidence("Terraform", {"terraform aws modules"}) is True


def test_multi_word_skill_matches_a_contained_phrase():
    assert _skill_matches_evidence("machine learning", {"a machine learning toolkit"}) is True
    assert _skill_matches_evidence("machine learning", {"machine shop inventory"}) is False


def test_ambiguous_short_skills_need_an_exact_token():
    # "go" must not be picked up from a longer phrase, even a tokenized one.
    assert _skill_matches_evidence("Go", {"go microservices"}) is False
    assert _skill_matches_evidence("Go", {"go"}) is True


def test_empty_and_degenerate_input():
    assert _skill_matches_evidence("", {"python"}) is False
    assert _skill_matches_evidence("   ", {"python"}) is False
    assert _skill_matches_evidence("Python", set()) is False
    assert _skill_matches_evidence("Python", {"", "   "}) is False


def test_matching_never_raises_on_odd_characters():
    for skill in ["C++", "F#", ".NET", "node.js", "a/b", "x|y", "(python)"]:
        assert _skill_matches_evidence(skill, {"python", "c++"}) in (True, False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def test_normalize_collapses_whitespace_and_trailing_punctuation():
    assert _normalize("  Machine   Learning.  ") == "machine learning"
    assert _normalize("Python,") == "python"


def test_tokens_preserve_language_distinguishing_characters():
    assert "c++" in _tokens("c++ and python")
    assert "c#" in _tokens("c# projects")
    assert "node.js" in _tokens("node.js server")


# ── Username extraction ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "field,expected",
    [
        ("https://github.com/octocat", "octocat"),
        ("http://github.com/octocat/", "octocat"),
        ("github.com/octocat", "octocat"),
        ("GitHub.com/Octo-Cat", "Octo-Cat"),
        ("octocat", "octocat"),
        ("https://github.com/octocat/some-repo", "octocat"),
    ],
)
def test_extract_username(field, expected):
    assert extract_username(field) == expected


@pytest.mark.parametrize("field", [None, "", "   ", "not a github url", "https://gitlab.com/octocat"])
def test_extract_username_rejects_non_github(field):
    assert extract_username(field) in (None, "")
