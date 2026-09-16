"""
The JD-match ranking, on both storage paths.

/match is the feature a recruiter uses to rank a shortlist against one job
description, and its ranking builder had no tests. Every field in a ranking
row comes out of a stored report blob, so none of it can be trusted to have
the type it should — `int("seventy")` raises and takes the whole status
endpoint down with it, and `list("python")` quietly turns one skill into six
single letters on the candidate's card.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.analysis import _jobs
from app.core.dependencies import get_db
from app.main import app
from app.services.queue import batch_store
from tests.fake_supabase import FakeSupabase

client = TestClient(app)


def signup(email, name):
    creds = {"email": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": name})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    payload = res.json()
    return {
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user_id": payload["user"]["id"],
    }


@pytest.fixture
def recruiter():
    return signup("match_owner@example.com", "Match Owner")


@pytest.fixture
def stranger():
    return signup("match_stranger@example.com", "Match Stranger")


def report(name, score, match_percent, matching=("python",), missing=("kubernetes",)):
    return {
        "candidate": {"name": name},
        "credibility": {"overall": score, "recommendation": "recommended"},
        "file_name": f"{name.lower().replace(' ', '_')}.pdf",
        "jd_match": {
            "match_percent": match_percent,
            "matching_skills": list(matching),
            "missing_skills": list(missing),
            "verdict": "strong_match" if match_percent >= 70 else "partial_match",
            "rationale": "Backed by the evidenced work.",
        },
    }


def seed(user_id, batch_id, reports: dict):
    job_ids = []
    for jid, blob in reports.items():
        rid = f"rep_{jid}"
        stored = dict(blob)
        stored["_owner_user_id"] = user_id
        _jobs[f"report_{rid}"] = stored
        _jobs[jid] = {
            "id": jid, "user_id": user_id, "batch_id": batch_id,
            "status": "complete", "stage": "complete", "progress": 100,
            "file_name": f"{jid}.pdf", "report_id": rid, "error": None,
        }
        job_ids.append(jid)
    batch_store.create_batch(None, batch_id, user_id, job_ids, total=len(job_ids))


class TestRanking:
    def test_candidates_are_ranked_by_how_well_they_match(self, recruiter):
        seed(recruiter["user_id"], "mb", {
            "m1": report("Anita Rao", 88, 91),
            "m2": report("Bharat Shah", 74, 55),
            "m3": report("Chetan Iyer", 66, 78),
        })
        res = client.get("/api/v1/match/mb/status", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        ranking = res.json()["ranking"]
        assert [r["candidate_name"] for r in ranking] == ["Anita Rao", "Chetan Iyer", "Bharat Shah"]
        assert [r["rank"] for r in ranking] == [1, 2, 3]
        assert ranking[0]["match_percent"] == 91
        assert ranking[0]["matching_skills"] == ["python"]
        assert ranking[0]["verdict"] == "strong_match"

    def test_someone_else_s_batch_is_refused(self, recruiter, stranger):
        seed(recruiter["user_id"], "mb", {"m1": report("Anita Rao", 88, 91)})
        assert client.get("/api/v1/match/mb/status", headers=stranger["headers"]).status_code == 403

    def test_an_unknown_batch_is_a_404(self, recruiter):
        assert client.get("/api/v1/match/nope/status", headers=recruiter["headers"]).status_code == 404

    def test_a_report_with_no_match_result_still_ranks_at_zero(self, recruiter):
        blob = report("Anita Rao", 88, 91)
        del blob["jd_match"]
        seed(recruiter["user_id"], "mb", {"m1": blob})
        ranking = client.get("/api/v1/match/mb/status", headers=recruiter["headers"]).json()["ranking"]
        assert ranking[0]["match_percent"] == 0
        assert ranking[0]["matching_skills"] == []
        assert ranking[0]["verdict"] == "unknown"


HOSTILE = [
    pytest.param({"jd_match": "strong match"}, id="match-is-a-string"),
    pytest.param({"jd_match": {"match_percent": "ninety"}}, id="percent-is-a-word"),
    pytest.param({"jd_match": {"match_percent": None}}, id="percent-is-null"),
    pytest.param({"jd_match": {"matching_skills": "python"}}, id="skills-is-a-string"),
    pytest.param({"jd_match": {"missing_skills": {"a": 1}}}, id="missing-is-a-dict"),
    pytest.param({"jd_match": {"verdict": 5, "rationale": []}}, id="verdict-is-a-number"),
    pytest.param({"credibility": {"overall": "seventy"}}, id="score-is-a-word"),
    pytest.param({"candidate": "not a dict"}, id="candidate-is-a-string"),
]


class TestTheRankingSurvivesOddData:
    @pytest.mark.parametrize("broken", HOSTILE)
    def test_one_odd_report_does_not_sink_the_ranking(self, recruiter, broken):
        good = report("Anita Rao", 88, 91)
        bad = {**report("Broken One", 50, 50), **broken}
        seed(recruiter["user_id"], "mb", {"m1": good, "m2": bad})

        res = client.get("/api/v1/match/mb/status", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        names = [r["candidate_name"] for r in res.json()["ranking"]]
        assert "Anita Rao" in names

    def test_a_single_skill_string_does_not_become_six_letters(self, recruiter):
        """`list("python")` is six single-character skills nobody claimed."""
        bad = report("Broken One", 50, 50)
        bad["jd_match"]["matching_skills"] = "python"
        seed(recruiter["user_id"], "mb", {"m1": bad})

        row = client.get("/api/v1/match/mb/status", headers=recruiter["headers"]).json()["ranking"][0]
        assert row["matching_skills"] == []

    def test_a_non_numeric_match_percent_does_not_error(self, recruiter):
        bad = report("Broken One", 50, 50)
        bad["jd_match"]["match_percent"] = "ninety-one"
        seed(recruiter["user_id"], "mb", {"m1": bad})

        res = client.get("/api/v1/match/mb/status", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        assert res.json()["ranking"][0]["match_percent"] == 0

    def test_the_csv_export_survives_it_too(self, recruiter):
        bad = report("Broken One", 50, 50)
        bad["jd_match"] = "strong match"
        seed(recruiter["user_id"], "mb", {"m1": report("Anita Rao", 88, 91), "m2": bad})

        res = client.get("/api/v1/match/mb/export.csv", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        assert "Anita Rao" in res.text


class TestRankingFromTheDatabase:
    def test_the_ranking_comes_from_the_stored_row_after_a_restart(self, recruiter):
        seed(recruiter["user_id"], "mb", {"m1": report("Anita Rao", 88, 91)})
        fake = FakeSupabase({"reports": [{
            "id": "rep_m1",
            "file_name": "anita.pdf",
            "candidate_name": "Anita Rao",
            "overall_score": 95,
            "recommendation": "recommended",
            "report_data": report("Anita Rao", 95, 97),
        }]})
        app.dependency_overrides[get_db] = lambda: fake
        try:
            row = client.get("/api/v1/match/mb/status", headers=recruiter["headers"]).json()["ranking"][0]
            assert row["overall_score"] == 95
            assert row["match_percent"] == 97
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_a_malformed_stored_row_does_not_error(self, recruiter):
        seed(recruiter["user_id"], "mb", {"m1": report("Anita Rao", 88, 91)})
        fake = FakeSupabase({"reports": [{
            "id": "rep_m1",
            "file_name": None,
            "candidate_name": "Anita Rao",
            "overall_score": "ninety",
            "recommendation": 12345,
            "report_data": {"jd_match": "strong"},
        }]})
        app.dependency_overrides[get_db] = lambda: fake
        try:
            res = client.get("/api/v1/match/mb/status", headers=recruiter["headers"])
            assert res.status_code == 200, res.text
            row = res.json()["ranking"][0]
            assert row["overall_score"] == 0
            assert row["match_percent"] == 0
            assert row["recommendation"] == "manual_review"
        finally:
            app.dependency_overrides.pop(get_db, None)
