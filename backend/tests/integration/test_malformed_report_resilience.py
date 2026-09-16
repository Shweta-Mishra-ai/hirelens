"""
One malformed report must not take the app down.

A report is a JSON blob, and blobs go wrong for ordinary reasons: a build
that wrote a different shape, a partial write, a field an older version did
not have. Every list, ranking and export in this app is built by walking
every report a user owns in one pass — so before the shape guards, a single
blob whose `candidate` was a string raised AttributeError and returned 500
for the entire dashboard. The recruiter saw no candidates at all, and no
error either, because an unhandled exception skipped the CORS middleware
and the browser would not let the app read the response.

Every test here mixes one good report with one deliberately broken one and
checks that the good one still arrives.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.analysis import _jobs
from app.core import local_db
from app.main import app

client = TestClient(app)

HOSTILE_SHAPES = [
    pytest.param({"candidate": "not a dict"}, id="candidate-is-a-string"),
    pytest.param({"credibility": "high"}, id="credibility-is-a-string"),
    pytest.param({"credibility": {"overall": "seventy"}}, id="score-is-a-word"),
    pytest.param({"credibility": {"recommendation": 12345}}, id="verdict-is-a-number"),
    pytest.param({"skills": ["python"]}, id="skills-is-a-list"),
    pytest.param({"skills": {"all_claimed": "python, django"}}, id="skills-is-a-sentence"),
    pytest.param({"experience": "seven years"}, id="experience-is-a-string"),
    pytest.param({"flags": "critical"}, id="flags-is-a-string"),
    pytest.param({"education": None}, id="education-is-null"),
    pytest.param({"interview_questions": {"a": 1}}, id="questions-is-a-dict"),
    pytest.param({"file_name": 42}, id="filename-is-a-number"),
    pytest.param({"career_trajectory": []}, id="trajectory-is-a-list"),
    pytest.param({}, id="empty-report"),
]


@pytest.fixture
def recruiter():
    creds = {"email": "malformed@example.com", "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "Mal Formed"})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    payload = res.json()
    return {
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user_id": payload["user"]["id"],
    }


def good_report(user_id):
    return {
        "candidate": {"name": "Anita Rao", "email": "anita@example.com"},
        "skills": {"all_claimed": ["python", "django"]},
        "experience": [{"company": "Acme", "title": "Engineer"}],
        "education": [{"institution": "IIT Bombay"}],
        "flags": [],
        "credibility": {"overall": 88, "recommendation": "recommended"},
        "file_name": "anita.pdf",
        "_owner_user_id": user_id,
    }


def put_in_memory(report_id, blob, user_id):
    stored = dict(blob)
    stored["_owner_user_id"] = user_id
    _jobs[f"report_{report_id}"] = stored


def put_on_disk(report_id, blob, user_id):
    stored = dict(blob)
    stored["_owner_user_id"] = user_id
    local_db.save_report(
        report_id=report_id,
        user_id=user_id,
        file_name="broken.pdf",
        candidate_name="Broken",
        overall_score=0,
        recommendation="manual_review",
        report_data=stored,
    )


@pytest.mark.parametrize("broken", HOSTILE_SHAPES)
class TestTheListSurvives:
    def test_the_dashboard_list_still_returns_the_good_report(self, recruiter, broken):
        put_in_memory("good", good_report(recruiter["user_id"]), recruiter["user_id"])
        put_in_memory("bad", broken, recruiter["user_id"])

        res = client.get("/api/v1/reports", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        names = [r["candidate_name"] for r in res.json()["reports"]]
        assert "Anita Rao" in names

    def test_search_still_works(self, recruiter, broken):
        put_in_memory("good", good_report(recruiter["user_id"]), recruiter["user_id"])
        put_in_memory("bad", broken, recruiter["user_id"])

        res = client.get("/api/v1/reports?search=anita", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        assert [r["candidate_name"] for r in res.json()["reports"]] == ["Anita Rao"]

    def test_sorting_still_works(self, recruiter, broken):
        put_in_memory("good", good_report(recruiter["user_id"]), recruiter["user_id"])
        put_in_memory("bad", broken, recruiter["user_id"])

        for sort in ("newest", "oldest", "score_desc", "score_asc", "name_asc"):
            res = client.get(f"/api/v1/reports?sort={sort}", headers=recruiter["headers"])
            assert res.status_code == 200, f"{sort}: {res.text}"

    def test_the_csv_export_still_works(self, recruiter, broken):
        put_in_memory("good", good_report(recruiter["user_id"]), recruiter["user_id"])
        put_in_memory("bad", broken, recruiter["user_id"])

        res = client.get("/api/v1/reports/export.csv", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        assert "Anita Rao" in res.text

    def test_the_pool_analytics_still_works(self, recruiter, broken):
        put_in_memory("good", good_report(recruiter["user_id"]), recruiter["user_id"])
        put_in_memory("bad", broken, recruiter["user_id"])

        res = client.get("/api/v1/reports/analytics", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        assert "distribution" in res.json()

    def test_opening_the_broken_report_itself_does_not_error(self, recruiter, broken):
        """Its own page may be mostly empty, but it must load."""
        put_in_memory("bad", broken, recruiter["user_id"])
        res = client.get("/api/v1/reports/bad", headers=recruiter["headers"])
        assert res.status_code == 200, res.text

    def test_a_broken_report_read_back_from_disk_is_also_safe(self, recruiter, broken):
        put_on_disk("disk-bad", broken, recruiter["user_id"])
        _jobs.pop("report_disk-bad", None)  # force the disk path

        assert client.get("/api/v1/reports", headers=recruiter["headers"]).status_code == 200
        assert client.get("/api/v1/reports/disk-bad", headers=recruiter["headers"]).status_code == 200


class TestSortingWithOrdinaryData:
    """Not a malformed-data case at all: a score of zero is what a failed
    analysis, or a genuinely poor candidate, produces. The local branch
    sorted on `value or ""`, which turned that 0 into a string and made
    Python refuse to compare it with the other rows' integers — so one
    zero-scoring candidate returned 500 for the whole list."""

    @pytest.fixture(autouse=True)
    def isolated(self, fresh_local_db):
        """A private SQLite file: these assert on exact ordering, so reports
        another test in this file persisted must not be in the list."""
        yield

    def test_score_sorting_works_when_a_candidate_scored_zero(self, recruiter):
        uid = recruiter["user_id"]
        put_in_memory("good", good_report(uid), uid)
        zero = good_report(uid)
        zero["candidate"] = {"name": "Zero Score"}
        zero["credibility"] = {"overall": 0, "recommendation": "high_risk"}
        put_in_memory("zero", zero, uid)

        high = client.get("/api/v1/reports?sort=score_desc", headers=recruiter["headers"])
        assert high.status_code == 200, high.text
        assert [r["candidate_name"] for r in high.json()["reports"]] == ["Anita Rao", "Zero Score"]

        low = client.get("/api/v1/reports?sort=score_asc", headers=recruiter["headers"])
        assert [r["candidate_name"] for r in low.json()["reports"]] == ["Zero Score", "Anita Rao"]

    def test_name_sorting_is_not_case_sensitive(self, recruiter):
        uid = recruiter["user_id"]
        for key, name in (("a", "anita rao"), ("b", "Bharat Shah"), ("c", "Chetan Iyer")):
            report = good_report(uid)
            report["candidate"] = {"name": name}
            put_in_memory(key, report, uid)

        res = client.get("/api/v1/reports?sort=name_asc", headers=recruiter["headers"])
        assert [r["candidate_name"] for r in res.json()["reports"]] == [
            "anita rao", "Bharat Shah", "Chetan Iyer"
        ]

    def test_the_csv_export_sorts_the_same_way(self, recruiter):
        uid = recruiter["user_id"]
        put_in_memory("good", good_report(uid), uid)
        zero = good_report(uid)
        zero["candidate"] = {"name": "Zero Score"}
        zero["credibility"] = {"overall": 0, "recommendation": "high_risk"}
        put_in_memory("zero", zero, uid)

        res = client.get("/api/v1/reports/export.csv?sort=score_desc", headers=recruiter["headers"])
        assert res.status_code == 200, res.text
        lines = [l for l in res.text.strip().splitlines() if l][1:]
        assert lines[0].startswith("Anita Rao")


class TestTheRestOfTheAppSurvives:
    @pytest.mark.parametrize("broken", HOSTILE_SHAPES)
    def test_verification_runs_on_a_broken_report(self, recruiter, broken, monkeypatch):
        import app.api.v1.endpoints.verify as verify_ep

        async def nothing(*args, **kwargs):
            return []

        async def no_github(username, skills):
            return {"status": "no_username"}

        monkeypatch.setattr(verify_ep, "verify_github", no_github)
        monkeypatch.setattr(verify_ep, "verify_education", nothing)
        monkeypatch.setattr(verify_ep, "verify_certifications", nothing)
        monkeypatch.setattr(verify_ep, "verify_experience_companies", nothing)

        put_in_memory("bad", broken, recruiter["user_id"])
        res = client.post("/api/v1/verify/bad/run", headers=recruiter["headers"])
        assert res.status_code == 200, res.text

    @pytest.mark.parametrize("broken", HOSTILE_SHAPES)
    def test_the_discuss_tab_opens_on_a_broken_report(self, recruiter, broken):
        put_in_memory("bad", broken, recruiter["user_id"])
        assert client.get("/api/v1/reports/bad/comments", headers=recruiter["headers"]).status_code == 200
        assert client.get("/api/v1/reports/bad/votes", headers=recruiter["headers"]).status_code == 200

    @pytest.mark.parametrize("broken", HOSTILE_SHAPES)
    def test_a_batch_ranking_survives_a_broken_member(self, recruiter, broken):
        from app.services.queue import batch_store

        uid = recruiter["user_id"]
        put_in_memory("rgood", good_report(uid), uid)
        put_in_memory("rbad", broken, uid)
        for jid, rid in (("jg", "rgood"), ("jb", "rbad")):
            _jobs[jid] = {
                "id": jid, "user_id": uid, "batch_id": "bm",
                "status": "complete", "stage": "complete", "progress": 100,
                "file_name": f"{jid}.pdf", "report_id": rid, "error": None,
            }
        batch_store.create_batch(None, "bm", uid, ["jg", "jb"], total=2)

        status = client.get("/api/v1/bulk/bm/status", headers=recruiter["headers"])
        assert status.status_code == 200, status.text
        assert "Anita Rao" in [r["candidate_name"] for r in status.json()["ranking"]]

        assert client.get("/api/v1/bulk/bm/export.csv", headers=recruiter["headers"]).status_code == 200
        assert client.get("/api/v1/bulk/bm/duplicates", headers=recruiter["headers"]).status_code == 200

    def test_the_stored_json_is_left_alone(self, recruiter):
        """The guard fixes what a reader sees; it does not quietly rewrite
        the recruiter's data on disk."""
        blob = {"candidate": "not a dict", "_owner_user_id": recruiter["user_id"]}
        put_on_disk("untouched", blob, recruiter["user_id"])
        client.get("/api/v1/reports/untouched", headers=recruiter["headers"])

        raw = local_db.get_report("untouched", recruiter["user_id"])
        assert raw["candidate"] == "not a dict"
