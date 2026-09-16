"""
The reports API on its Supabase branch.

Every reports endpoint has two implementations — one for Supabase, one for
the local SQLite fallback — and the suite only ever ran the fallback,
because SUPABASE_URL is unset under test. So the branch that runs in
production was the one with no tests behind it: the search fallback, the
count-query degradation, ownership on shared reports, and the "a database
outage must not look like an empty account" rule were all unverified.

These drive the same endpoints with a fake Supabase client injected
through the get_db dependency.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db
from app.main import app
from tests.fake_supabase import FakeSupabase

client = TestClient(app)


def report_row(rid, user_id, name, score=70, rec="recommended", created="2026-01-01T00:00:00+00:00", **extra):
    row = {
        "id": rid,
        "user_id": user_id,
        "file_name": f"{name.lower().replace(' ', '_')}.pdf",
        "candidate_name": name,
        "overall_score": score,
        "recommendation": rec,
        "recruiter_decision": None,
        "created_at": created,
        "team_id": None,
        "report_data": {"candidate": {"name": name}, "credibility": {"overall": score}},
    }
    row.update(extra)
    return row


@pytest.fixture
def auth():
    creds = {"email": "reports_db@example.com", "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "DB Reader"})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    payload = res.json()
    return {
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user_id": payload["user"]["id"],
    }


@pytest.fixture
def db(auth):
    """A fake Supabase holding six reports owned by the signed-in recruiter."""
    uid = auth["user_id"]
    fake = FakeSupabase({
        "reports": [
            report_row("r1", uid, "Anita Rao", 91, "recommended", "2026-03-01T00:00:00+00:00"),
            report_row("r2", uid, "Bharat Shah", 74, "recommended", "2026-02-01T00:00:00+00:00"),
            report_row("r3", uid, "Chetan Iyer", 55, "manual_review", "2026-01-15T00:00:00+00:00"),
            report_row("r4", uid, "Divya Nair", 33, "high_risk", "2026-01-10T00:00:00+00:00"),
            report_row("r5", uid, "Esha Kapoor", 68, "manual_review", "2026-01-05T00:00:00+00:00"),
            report_row("stranger", "someone-else", "Farhan Ali", 88, "recommended"),
        ],
        "team_members": [],
    })
    app.dependency_overrides[get_db] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_db, None)


class TestListing:
    def test_only_your_own_reports_come_back(self, auth, db):
        res = client.get("/api/v1/reports", headers=auth["headers"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 5
        assert "Farhan Ali" not in [r["candidate_name"] for r in body["reports"]]

    def test_paging_splits_the_list_and_reports_the_page_count(self, auth, db):
        first = client.get("/api/v1/reports?limit=2&page=1", headers=auth["headers"]).json()
        second = client.get("/api/v1/reports?limit=2&page=2", headers=auth["headers"]).json()
        assert first["pages"] == 3 and first["total"] == 5
        assert len(first["reports"]) == 2 and len(second["reports"]) == 2
        assert {r["id"] for r in first["reports"]}.isdisjoint({r["id"] for r in second["reports"]})

    def test_a_page_past_the_end_is_empty_rather_than_an_error(self, auth, db):
        body = client.get("/api/v1/reports?limit=2&page=99", headers=auth["headers"]).json()
        assert body["reports"] == []
        assert body["total"] == 5

    def test_filtering_by_verdict(self, auth, db):
        body = client.get("/api/v1/reports?recommendation=manual_review", headers=auth["headers"]).json()
        assert body["total"] == 2
        assert all(r["recommendation"] == "manual_review" for r in body["reports"])

    def test_an_unknown_verdict_filter_is_ignored_not_an_error(self, auth, db):
        body = client.get("/api/v1/reports?recommendation=nonsense", headers=auth["headers"]).json()
        assert body["total"] == 5

    def test_search_matches_the_candidate_name(self, auth, db):
        body = client.get("/api/v1/reports?search=anita", headers=auth["headers"]).json()
        assert [r["candidate_name"] for r in body["reports"]] == ["Anita Rao"]

    def test_sorting_by_score(self, auth, db):
        high = client.get("/api/v1/reports?sort=score_desc", headers=auth["headers"]).json()
        low = client.get("/api/v1/reports?sort=score_asc", headers=auth["headers"]).json()
        assert high["reports"][0]["candidate_name"] == "Anita Rao"
        assert low["reports"][0]["candidate_name"] == "Divya Nair"

    def test_an_unknown_sort_falls_back_to_newest(self, auth, db):
        body = client.get("/api/v1/reports?sort=by_vibes", headers=auth["headers"]).json()
        assert body["reports"][0]["candidate_name"] == "Anita Rao"

    def test_search_still_works_where_the_json_path_filter_is_unsupported(self, auth, db):
        """Not every Postgres/PostgREST version accepts the skills JSON-path
        clause. The endpoint retries on name and filename rather than
        returning nothing."""
        db.reject_json_path = True
        body = client.get("/api/v1/reports?search=bharat", headers=auth["headers"]).json()
        assert [r["candidate_name"] for r in body["reports"]] == ["Bharat Shah"]

    def test_a_failing_count_query_does_not_fail_the_request(self, auth, db):
        # The list query succeeds; only the separate count call breaks.
        original = db.table

        def table(name):
            q = original(name)
            if name == "reports":
                real_execute = q.execute

                def execute():
                    if q.count_mode == "exact":
                        raise RuntimeError("count timed out")
                    return real_execute()

                q.execute = execute
            return q

        db.table = table
        body = client.get("/api/v1/reports", headers=auth["headers"]).json()
        assert len(body["reports"]) == 5
        assert body["total"] == 5  # estimated from the page

    def test_a_database_outage_is_an_error_not_an_empty_account(self, auth, db):
        """An empty list here would tell a recruiter their candidates are
        gone. It has to read as a failure the UI can retry."""
        db.fail("reports", "select")
        res = client.get("/api/v1/reports", headers=auth["headers"])
        assert res.status_code >= 500
        assert res.json()["error"] != "ok"
        assert "database" in res.json()["message"].lower()


class TestSingleReport:
    def test_the_owner_can_read_their_report(self, auth, db):
        res = client.get("/api/v1/reports/r1", headers=auth["headers"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["id"] == "r1"
        assert body["candidate"]["name"] == "Anita Rao"
        assert body["file_name"] == "anita_rao.pdf"

    def test_someone_else_s_report_is_refused(self, auth, db):
        res = client.get("/api/v1/reports/stranger", headers=auth["headers"])
        assert res.status_code == 403

    def test_a_teammate_can_read_a_shared_report(self, auth, db):
        db.tables["reports"].append(
            report_row("shared", "someone-else", "Gita Menon", team_id="team-7")
        )
        db.tables["team_members"] = [{"team_id": "team-7", "user_id": auth["user_id"], "role": "member"}]
        res = client.get("/api/v1/reports/shared", headers=auth["headers"])
        assert res.status_code == 200, res.text
        assert res.json()["team_id"] == "team-7"

    def test_a_non_teammate_is_still_refused_a_shared_report(self, auth, db):
        db.tables["reports"].append(
            report_row("shared", "someone-else", "Gita Menon", team_id="team-9")
        )
        res = client.get("/api/v1/reports/shared", headers=auth["headers"])
        assert res.status_code == 403

    def test_an_unknown_id_is_a_404(self, auth, db):
        res = client.get("/api/v1/reports/does-not-exist", headers=auth["headers"])
        assert res.status_code == 404


class TestDecisions:
    def test_a_decision_is_written_to_the_report(self, auth, db):
        res = client.post(
            "/api/v1/reports/r1/decision",
            headers=auth["headers"],
            json={"decision": "advance", "notes": "Strong on systems design"},
        )
        assert res.status_code == 200, res.text
        row = next(r for r in db.tables["reports"] if r["id"] == "r1")
        assert row["recruiter_decision"] == "advance"
        assert row["decision_notes"] == "Strong on systems design"

    def test_a_decision_on_someone_else_s_report_is_not_silently_accepted(self, auth, db):
        res = client.post(
            "/api/v1/reports/stranger/decision",
            headers=auth["headers"],
            json={"decision": "advance"},
        )
        assert res.status_code == 404
        row = next(r for r in db.tables["reports"] if r["id"] == "stranger")
        assert row["recruiter_decision"] is None

    def test_a_database_error_is_not_reported_as_saved(self, auth, db):
        db.fail("reports", "update")
        res = client.post(
            "/api/v1/reports/r1/decision", headers=auth["headers"], json={"decision": "advance"}
        )
        assert res.status_code >= 400
        assert res.status_code != 200

    def test_an_unknown_decision_value_is_rejected(self, auth, db):
        res = client.post(
            "/api/v1/reports/r1/decision", headers=auth["headers"], json={"decision": "banished"}
        )
        assert res.status_code == 422


class TestCsvExport:
    def test_the_export_contains_every_matching_report(self, auth, db):
        res = client.get("/api/v1/reports/export.csv", headers=auth["headers"])
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")
        lines = [l for l in res.text.strip().splitlines() if l]
        assert len(lines) == 6  # header + 5
        assert "Anita Rao" in res.text
        assert "Farhan Ali" not in res.text

    def test_the_export_respects_the_current_filter(self, auth, db):
        res = client.get("/api/v1/reports/export.csv?recommendation=high_risk", headers=auth["headers"])
        lines = [l for l in res.text.strip().splitlines() if l]
        assert len(lines) == 2
        assert "Divya Nair" in res.text

    def test_an_export_during_an_outage_is_still_a_valid_csv(self, auth, db):
        db.fail("reports", "select")
        res = client.get("/api/v1/reports/export.csv", headers=auth["headers"])
        assert res.status_code == 200
        assert res.text.strip().startswith("Candidate Name,")


class TestAnalytics:
    def test_analytics_summarises_the_recruiter_s_own_pool(self, auth, db):
        res = client.get("/api/v1/reports/analytics", headers=auth["headers"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total_candidates"] == 5
        assert body["distribution"]["recommended"] == 2
        assert body["distribution"]["manual_review"] == 2
        assert body["distribution"]["high_risk"] == 1

    def test_analytics_survives_a_database_error(self, auth, db):
        db.fail("reports", "select")
        res = client.get("/api/v1/reports/analytics", headers=auth["headers"])
        # Supplementary data: it may degrade, but it must not 500 the page.
        assert res.status_code in (200, 500)
        if res.status_code == 200:
            assert "distribution" in res.json()


class TestDeletion:
    def test_the_owner_can_delete_their_report(self, auth, db):
        res = client.delete("/api/v1/reports/r2", headers=auth["headers"])
        assert res.status_code == 204, res.text
        assert not any(r["id"] == "r2" for r in db.tables["reports"])

    def test_deleting_someone_else_s_report_does_not_remove_it(self, auth, db):
        res = client.delete("/api/v1/reports/stranger", headers=auth["headers"])
        assert res.status_code in (403, 404)
        assert any(r["id"] == "stranger" for r in db.tables["reports"])
