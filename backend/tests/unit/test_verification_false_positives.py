"""
HireLens — Verification must not confirm things it has not confirmed

A false "verified" is the worst output this product can produce. It tells a
recruiter a claim has been independently corroborated when it has not, and it
is acted on — a candidate is advanced, or a competing one is not. Reporting
nothing is always better than reporting something untrue.

Run: cd backend && python -m pytest tests/unit/test_verification_false_positives.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest

from app.services.verify.education_verify import (
    _candidate_queries, _names_agree, _best_match,
)
from app.services.verify.certification_verify import (
    _visible_text, _name_on_page, _name_parts, _NEGATIVE_MARKERS,
)
from app.services.verify.trust_assessment import compute_trust_assessment


# ── Education ───────────────────────────────────────────────────────────────
class TestEducationNameAgreement:
    @pytest.mark.parametrize(
        "claimed,matched",
        [
            # The registry answers a substring search, so a one-word query
            # returns a real institution that has nothing to do with the claim.
            ("Stanford Technical College", "Technical University of Munich"),
            ("Harvard Institute of Technology", "Harvard University"),
            ("Oxford Brookes University", "University of Oxford"),
            ("Springfield State College", "Springfield University"),
        ],
    )
    def test_a_different_institution_does_not_agree(self, claimed, matched):
        assert _names_agree(claimed, matched) is False

    @pytest.mark.parametrize(
        "claimed,matched",
        [
            ("Indian Institute of Technology Delhi", "Indian Institute of Technology Delhi"),
            ("Delhi Technological University, Main Campus", "Delhi Technological University"),
            ("University of Oxford", "University of Oxford"),
            ("mit", "Massachusetts Institute of Technology MIT"),
        ],
    )
    def test_the_same_institution_agrees(self, claimed, matched):
        assert _names_agree(claimed, matched) is True

    def test_generic_words_alone_cannot_carry_a_match(self):
        """"The University" shares every word with thousands of entries."""
        assert _names_agree("The University", "University of Cambridge") is False

    def test_case_and_punctuation_do_not_matter(self):
        assert _names_agree("ST. XAVIER'S COLLEGE", "St Xaviers College") is True


class TestEducationQueryConfidence:
    def test_the_full_name_is_a_strong_query(self):
        queries = _candidate_queries("Delhi Technological University")
        assert queries[0] == ("Delhi Technological University", True)

    def test_the_single_word_fallback_is_never_strong(self):
        """This is the query that finds an unrelated institution. It may
        surface a suggestion; it may not confirm one."""
        queries = _candidate_queries("Stanford Technical College")
        single_word = [q for q, strong in queries if " " not in q]
        assert single_word, "expected a last-resort single-word query"
        for q, strong in queries:
            if " " not in q:
                assert strong is False

    def test_a_known_abbreviation_expansion_stays_strong(self):
        queries = _candidate_queries("IIT Delhi")
        expanded = [q for q, _ in queries if "indian institute" in q.lower()]
        assert expanded
        assert all(strong for q, strong in queries if "indian institute" in q.lower())

    def test_trimming_a_campus_qualifier_stays_strong(self):
        queries = _candidate_queries("Delhi Technological University (Main Campus)")
        assert ("Delhi Technological University", True) in queries


class TestEducationBestMatch:
    def test_the_closest_name_wins_not_the_first_one(self):
        matches = [
            {"name": "Technical University of Munich"},
            {"name": "Stanford Technical College"},
        ]
        assert _best_match(matches, "Stanford Technical College")["name"] == (
            "Stanford Technical College"
        )


class TestTrustScoreIgnoresUnconfirmedInstitutions:
    def _assess(self, education):
        return compute_trust_assessment(
            ai_content_analysis={"ai_likelihood": "low"},
            verification={"education": education},
            overall_score=60,
        )

    def test_a_confirmed_institution_counts(self):
        result = self._assess([{"institution": "X", "status": "verified"}])
        assert any("registry" in r.lower() for r in result["reasoning"])

    def test_a_possible_match_counts_for_nothing(self):
        """It used to be reported as verified, worth +10 and a line reading
        "institution(s) confirmed in university registry" — for a name the
        registry never actually matched."""
        possible = self._assess([{"institution": "X", "status": "possible_match"}])
        neither = self._assess([])
        assert possible["score"] == neither["score"]
        assert not any("confirmed" in r.lower() for r in possible["reasoning"])

    def test_a_possible_match_is_not_counted_against_them_either(self):
        possible = self._assess([{"institution": "X", "status": "possible_match"}])
        not_found = self._assess([{"institution": "X", "status": "not_found"}])
        assert possible["score"] > not_found["score"]


# ── Certifications ──────────────────────────────────────────────────────────
class TestCertificationNameMatching:
    PAGE = _visible_text(
        "<html><head><script>var u='/verify?name=Li';</script>"
        "<style>.link{}</style></head>"
        "<body>Announcement. Client portal. Link here.</body></html>"
    )

    @pytest.mark.parametrize("name", ["Li", "An", "Ann", "Al"])
    def test_a_short_name_is_not_found_in_incidental_words(self, name):
        """A plain substring test matched these inside "Link", "Client" and
        "Announcement", and marked the credential verified."""
        assert _name_on_page(name, self.PAGE) is False

    def test_markup_is_not_searched(self):
        """The name in a script variable or a meta tag is not the name on the
        certificate — and on many credential sites the requested URL contains
        the name being looked for, so the check would confirm itself."""
        page = _visible_text(
            '<html><head><meta name="author" content="Priya Raghunathan"></head>'
            "<body>Nothing to see.</body></html>"
        )
        assert _name_on_page("Priya Raghunathan", page) is False

    def test_a_real_certificate_page_matches(self):
        page = _visible_text(
            "<html><body><h1>Certificate of Completion</h1>"
            "<p>This certifies that Priya Raghunathan completed the course.</p></body></html>"
        )
        assert _name_on_page("Priya Raghunathan", page) is True

    def test_someone_elses_certificate_does_not_match(self):
        page = _visible_text("<body>This certifies that Priya Raghunathan completed it.</body>")
        assert _name_on_page("Rahul Mehta", page) is False

    def test_a_partial_name_is_not_enough(self):
        """Sharing a surname with the certificate holder is not holding it."""
        page = _visible_text("<body>Awarded to Priya Raghunathan.</body>")
        assert _name_on_page("Anjali Raghunathan", page) is False

    def test_a_name_inside_a_longer_word_does_not_count(self):
        page = _visible_text("<body>Certificate issued to the Anderson Institute.</body>")
        assert _name_on_page("And Erson", page) is False

    def test_a_single_long_name_can_still_match(self):
        page = _visible_text("<body>Awarded to Madonna.</body>")
        assert _name_on_page("Madonna", page) is True

    def test_an_empty_name_never_matches(self):
        assert _name_on_page("", _visible_text("<body>anything</body>")) is False
        assert _name_parts("") == []


class TestCertificationNegativePages:
    @pytest.mark.parametrize("phrase", ["not found", "credential not found", "has been revoked"])
    def test_a_page_saying_no_such_credential_is_recognised(self, phrase):
        page = _visible_text(f"<body>Priya Raghunathan — {phrase}</body>")
        assert any(marker in page for marker in _NEGATIVE_MARKERS)

    def test_such_a_page_would_otherwise_have_matched_the_name(self):
        """The name IS on the page — echoed back in the error. Without the
        negative-marker check, a "not found" page reads as a confirmation."""
        page = _visible_text("<body>No certificate found for Priya Raghunathan.</body>")
        assert _name_on_page("Priya Raghunathan", page) is True
        assert any(marker in page for marker in _NEGATIVE_MARKERS)


class TestVisibleText:
    def test_scripts_and_styles_are_dropped_entirely(self):
        text = _visible_text("<style>body{color:red}</style><script>alert(1)</script><p>Hello</p>")
        assert "color" not in text and "alert" not in text
        assert "hello" in text

    def test_it_does_not_choke_on_broken_markup(self):
        assert _visible_text("<p>unclosed") == "unclosed"
        assert _visible_text("") == ""
        assert _visible_text(None) == ""
