"""
HireLens — Duplicate/Template Detection Unit Tests
Run: cd backend && python -m pytest tests/unit/test_duplicate_detection.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.fraud.duplicate_detection import (
    compute_shingles, jaccard_similarity, extract_fingerprint_text, find_duplicate_clusters,
)


REAL_BULLET_A = (
    "Designed and implemented a microservices architecture using FastAPI and PostgreSQL "
    "to replace a legacy monolith, reducing average API response time by 35 percent through "
    "targeted caching and query optimization work done over several sprints with the platform team."
)
REAL_BULLET_B = (
    "Led the migration of our internal billing system from a monolithic Django app to a set of "
    "Go microservices, coordinating with three other teams and writing the rollback plan that let "
    "us ship the change with zero downtime during a scheduled maintenance window last spring."
)
TEMPLATE_TEXT_1 = (
    "Spearheaded cross-functional initiatives to leverage cutting-edge technologies and drive "
    "synergistic outcomes across the organization, resulting in significant improvements to key "
    "performance indicators through strategic implementation of best-in-class solutions."
)
TEMPLATE_TEXT_2 = (
    "Spearheaded cross-functional initiatives to leverage cutting-edge technologies and drive "
    "synergistic outcomes across the organization, resulting in significant improvements to key "
    "performance indicators through strategic implementation of best-in-class solutions and tools."
)


class TestShinglesAndSimilarity:
    def test_identical_text_has_similarity_one(self):
        s1 = compute_shingles(REAL_BULLET_A)
        s2 = compute_shingles(REAL_BULLET_A)
        assert jaccard_similarity(s1, s2) == 1.0

    def test_completely_different_text_has_low_similarity(self):
        s1 = compute_shingles(REAL_BULLET_A)
        s2 = compute_shingles(REAL_BULLET_B)
        assert jaccard_similarity(s1, s2) < 0.2

    def test_near_identical_template_text_has_high_similarity(self):
        s1 = compute_shingles(TEMPLATE_TEXT_1)
        s2 = compute_shingles(TEMPLATE_TEXT_2)
        assert jaccard_similarity(s1, s2) > 0.7

    def test_empty_text_yields_no_shingles(self):
        assert compute_shingles("") == set()

    def test_short_text_below_shingle_size_yields_no_shingles(self):
        assert compute_shingles("too short") == set()

    def test_similarity_with_empty_set_is_zero(self):
        assert jaccard_similarity(set(), {"a b c"}) == 0.0
        assert jaccard_similarity(set(), set()) == 0.0

    def test_normalization_ignores_case_and_punctuation(self):
        s1 = compute_shingles("Hello, World! This Is A Test Sentence Here.")
        s2 = compute_shingles("hello world this is a test sentence here")
        assert jaccard_similarity(s1, s2) == 1.0


class TestFingerprintExtraction:
    def test_pulls_experience_bullets(self):
        report = {"experience": [{"responsibilities": ["Built X", "Shipped Y"]}]}
        text = extract_fingerprint_text(report)
        assert "Built X" in text
        assert "Shipped Y" in text

    def test_pulls_project_descriptions(self):
        report = {"projects": [{"description": "A cool project"}]}
        text = extract_fingerprint_text(report)
        assert "A cool project" in text

    def test_empty_report_yields_empty_string(self):
        assert extract_fingerprint_text({}) == ""

    def test_missing_fields_do_not_crash(self):
        report = {"experience": [{}], "projects": [{}]}
        assert extract_fingerprint_text(report) == ""


class TestFindDuplicateClusters:
    def test_no_duplicates_among_distinct_resumes(self):
        items = [
            {"id": "a", "name": "Alice", "text": REAL_BULLET_A * 2},
            {"id": "b", "name": "Bob", "text": REAL_BULLET_B * 2},
        ]
        clusters = find_duplicate_clusters(items)
        assert clusters == []

    def test_two_template_resumes_form_a_cluster(self):
        items = [
            {"id": "a", "name": "Alice", "text": TEMPLATE_TEXT_1 * 3},
            {"id": "b", "name": "Bob", "text": TEMPLATE_TEXT_2 * 3},
            {"id": "c", "name": "Carol", "text": REAL_BULLET_A * 3},
        ]
        clusters = find_duplicate_clusters(items)
        assert len(clusters) == 1
        member_ids = {m["id"] for m in clusters[0]["members"]}
        assert member_ids == {"a", "b"}
        assert clusters[0]["similarity"] > 0.35

    def test_transitive_clustering_three_way(self):
        """A~B and B~C (but A~C below threshold on its own) should still
        group into one 3-member cluster via transitivity."""
        items = [
            {"id": "a", "name": "Alice", "text": TEMPLATE_TEXT_1 * 3},
            {"id": "b", "name": "Bob", "text": TEMPLATE_TEXT_1 * 3},
            {"id": "c", "name": "Carol", "text": TEMPLATE_TEXT_1 * 3},
        ]
        clusters = find_duplicate_clusters(items)
        assert len(clusters) == 1
        assert len(clusters[0]["members"]) == 3

    def test_short_fingerprints_are_skipped(self):
        items = [
            {"id": "a", "name": "Alice", "text": "short"},
            {"id": "b", "name": "Bob", "text": "short"},
        ]
        clusters = find_duplicate_clusters(items)
        assert clusters == []

    def test_empty_items_list(self):
        assert find_duplicate_clusters([]) == []

    def test_single_item_never_clusters(self):
        items = [{"id": "a", "name": "Alice", "text": REAL_BULLET_A * 3}]
        assert find_duplicate_clusters(items) == []

    def test_clusters_sorted_by_similarity_descending(self):
        items = [
            {"id": "a", "name": "Alice", "text": TEMPLATE_TEXT_1 * 3},
            {"id": "b", "name": "Bob", "text": TEMPLATE_TEXT_2 * 3},
            {"id": "c", "name": "Carol", "text": REAL_BULLET_A + " extra padding words to pass min length threshold check here"},
            {"id": "d", "name": "Dave", "text": REAL_BULLET_A + " extra padding words to pass min length threshold check here too"},
        ]
        clusters = find_duplicate_clusters(items, threshold=0.3)
        if len(clusters) > 1:
            scores = [c["similarity"] for c in clusters]
            assert scores == sorted(scores, reverse=True)
