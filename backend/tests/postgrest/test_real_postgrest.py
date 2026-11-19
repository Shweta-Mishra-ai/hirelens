"""
The Supabase path, against a real PostgREST and Postgres.

Every other Supabase-path test uses tests/fake_supabase.py. The fake is
careful, but it is our reading of PostgREST, so a query PostgREST itself
would reject — a JSON-path select, an `or` filter, an upsert's conflict
target, an exact count — can pass all of them. These run the same endpoints
through the real supabase-py client against the real server.

Skipped unless a stack is configured. scripts/postgrest_e2e.sh starts one
(Postgres 16 with every file in sql/ applied, PostgREST, and the /rest/v1 mapping
Supabase's gateway provides) and runs this file:

    HIRELENS_E2E_SUPABASE_URL     e.g. http://127.0.0.1:54321
    HIRELENS_E2E_SERVICE_KEY      a service_role JWT for that PostgREST
    HIRELENS_E2E_USERS            "uuid:email,uuid:email,uuid:email" — rows
                                  already present in auth.users
    HIRELENS_E2E_DB_CONTAINER     the Postgres container, for the one test
                                  that must delete from auth.users (no GoTrue
                                  runs here); that test is skipped without it
"""

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

URL = os.environ.get("HIRELENS_E2E_SUPABASE_URL")
KEY = os.environ.get("HIRELENS_E2E_SERVICE_KEY")
USERS = [
    tuple(pair.split(":", 1))
    for pair in (os.environ.get("HIRELENS_E2E_USERS") or "").split(",")
    if ":" in pair
]

pytestmark = pytest.mark.skipif(
    not (URL and KEY and len(USERS) >= 3),
    reason="real PostgREST stack not configured (see scripts/postgrest_e2e.sh)",
)

PDF = b"%PDF-1.4\n" + b"0" * 2048
RESUME_TEXT = "Experience\nEducation\nSkills\nPython Go PostgreSQL\n" * 6


@pytest.fixture(scope="module")
def db():
    from supabase import create_client

    return create_client(URL, KEY)


@pytest.fixture(scope="module")
def app_with_db(db):
    from app.core.dependencies import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    yield app
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="module")
def client(app_with_db):
    return TestClient(app_with_db)


def _headers(user):
    from app.core.security import create_access_token

    uid, email = user
    return {"Authorization": f"Bearer {create_access_token({'sub': uid, 'email': email})}"}


@pytest.fixture(scope="module")
def owner():
    return USERS[0]


@pytest.fixture(scope="module")
def teammate():
    return USERS[1]


@pytest.fixture(scope="module")
def stranger():
    return USERS[2]


def _report(name, email, skills, score=80, rec="recommended"):
    return {
        "candidate": {"name": name, "email": email},
        "credibility": {"overall": score, "recommendation": rec},
        "skills": {"all_claimed": skills},
        "flags": [{"category": "Timeline", "severity": "low", "description": "gap"}],
        "experience": [{"role": "Engineer", "company": "Acme", "responsibilities": ["Built things"]}],
        "projects": [],
    }


def _analyse(client, user, report, filename="cv.pdf"):
    """Upload through the real pipeline, with only the parser and model stubbed."""
    from app.api.v1.endpoints import analysis as analysis_ep

    with patch.object(analysis_ep, "extract_text", return_value=RESUME_TEXT), \
         patch.object(analysis_ep, "looks_like_resume", return_value=(True, None)), \
         patch.object(analysis_ep.engine, "run", new=AsyncMock(return_value=report)):
        res = client.post(
            "/api/v1/analysis/upload",
            headers=_headers(user),
            files={"file": (filename, PDF, "application/pdf")},
        )
    assert res.status_code == 200, res.text
    job_id = res.json()["job_id"]
    status = client.get(f"/api/v1/analysis/{job_id}/status", headers=_headers(user)).json()
    assert status["status"] == "complete", status
    return status["report_id"], job_id


@pytest.fixture(scope="module")
def reports(client, owner, db):
    db.table("reports").delete().eq("user_id", owner[0]).execute()
    made = {
        "anita": _analyse(client, owner, _report("Anita Rao", "anita@example.com", ["Python", "Kubernetes"], 91), "anita.pdf")[0],
        "jose": _analyse(client, owner, _report("José Álvarez", "jose@example.com", ["Go"], 64, "manual_review"), "jose.pdf")[0],
        "formula": _analyse(client, owner, _report('=HYPERLINK("http://x","y")', None, ["Excel"], 40, "high_risk"), "f.pdf")[0],
    }
    return made


class TestReportsAgainstPostgREST:
    def test_the_insert_landed_with_its_jsonb(self, db, reports):
        row = db.table("reports").select("id,candidate_name,report_data").eq("id", reports["anita"]).single().execute().data
        assert row["candidate_name"] == "Anita Rao"
        assert row["report_data"]["skills"]["all_claimed"] == ["Python", "Kubernetes"]

    def test_listing_with_an_exact_count(self, client, owner, reports):
        body = client.get("/api/v1/reports?limit=2", headers=_headers(owner)).json()
        assert body["total"] == 3
        assert len(body["reports"]) == 2
        assert body["pages"] == 2

    def test_search_by_name_including_accents(self, client, owner, reports):
        names = [r["candidate_name"] for r in client.get("/api/v1/reports?search=José", headers=_headers(owner)).json()["reports"]]
        assert names == ["José Álvarez"]

    def test_search_by_skill_uses_the_json_path(self, client, owner, reports):
        res = client.get("/api/v1/reports?search=kubernetes", headers=_headers(owner))
        assert res.status_code == 200, res.text
        assert [r["candidate_name"] for r in res.json()["reports"]] == ["Anita Rao"]

    def test_sorting_by_score(self, client, owner, reports):
        scores = [r["overall_score"] for r in client.get("/api/v1/reports?sort=score_asc", headers=_headers(owner)).json()["reports"]]
        assert scores == sorted(scores)

    def test_analytics_reads_json_paths_not_blobs(self, client, owner, reports):
        res = client.get("/api/v1/reports/analytics", headers=_headers(owner))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total_candidates"] == 3
        assert body["distribution"] == {"recommended": 1, "manual_review": 1, "high_risk": 1}
        assert {"skill": "Python", "count": 1} in body["top_skills"]
        assert body["risk_categories"].get("timeline") == 3

    def test_csv_export_with_a_skill_search_and_formula_guard(self, client, owner, reports):
        res = client.get("/api/v1/reports/export.csv", headers=_headers(owner))
        assert res.status_code == 200, res.text
        assert "'=HYPERLINK" in res.text
        res = client.get("/api/v1/reports/export.csv?search=python", headers=_headers(owner))
        assert res.status_code == 200 and "Anita Rao" in res.text and "José" not in res.text

    def test_a_stranger_cannot_read_a_report(self, client, stranger, reports):
        assert client.get(f"/api/v1/reports/{reports['anita']}", headers=_headers(stranger)).status_code == 403

    def test_a_decision_is_recorded(self, client, owner, db, reports):
        res = client.post(f"/api/v1/reports/{reports['jose']}/decision", headers=_headers(owner), json={"decision": "advance", "notes": "strong"})
        assert res.status_code == 200, res.text
        row = db.table("reports").select("recruiter_decision,decision_notes").eq("id", reports["jose"]).single().execute().data
        assert row == {"recruiter_decision": "advance", "decision_notes": "strong"}

    def test_a_delivered_notification_is_stamped(self, client, owner, db, reports):
        with patch("app.services.email.sender.send_raw_email", new=AsyncMock(return_value=True)):
            res = client.post(
                f"/api/v1/reports/{reports['anita']}/notify",
                headers=_headers(owner),
                json={"decision": "advance", "subject": "Next steps", "body": "Hello"},
            )
        assert res.status_code == 200 and res.json()["email_sent"] is True
        row = db.table("reports").select("candidate_notified_at,candidate_notified_decision").eq("id", reports["anita"]).single().execute().data
        assert row["candidate_notified_at"] and row["candidate_notified_decision"] == "advance"

    def test_verification_persists_to_the_row(self, client, owner, db, reports):
        empty = AsyncMock(return_value=[])
        with patch("app.api.v1.endpoints.verify.verify_github", new=AsyncMock(return_value={"status": "skipped"})), \
             patch("app.api.v1.endpoints.verify.verify_education", new=empty), \
             patch("app.api.v1.endpoints.verify.verify_certifications", new=empty), \
             patch("app.api.v1.endpoints.verify.verify_experience_companies", new=empty):
            res = client.post(f"/api/v1/verify/{reports['jose']}/run", headers=_headers(owner), json={})
        assert res.status_code == 200, res.text
        row = db.table("reports").select("report_data").eq("id", reports["jose"]).single().execute().data
        assert "verification" in row["report_data"]

    def test_copilot_notes_round_trip(self, client, owner, reports):
        payload = {"scorecard": [{"category": "technical_depth", "score": 4}], "interview_notes": "Solid."}
        assert client.post(f"/api/v1/reports/{reports['anita']}/copilot", headers=_headers(owner), json=payload).status_code == 200
        got = client.get(f"/api/v1/reports/{reports['anita']}/copilot", headers=_headers(owner)).json()["copilot"]
        assert got["interview_notes"] == "Solid."


class TestBatchesAgainstPostgREST:
    @pytest.fixture
    def batch(self, owner, reports):
        from app.api.v1.endpoints.analysis import _jobs
        from app.services.queue import batch_store

        batch_id = f"e2e-{uuid.uuid4()}"
        job_ids = []
        for name, rid in reports.items():
            jid = f"{batch_id}-{name}"
            _jobs[jid] = {"id": jid, "user_id": owner[0], "status": "complete", "stage": "complete",
                          "progress": 100, "file_name": f"{name}.pdf", "report_id": rid, "error": None}
            job_ids.append(jid)
        batch_store.create_batch(None, batch_id, owner[0], job_ids, total=len(job_ids))
        batch_store.release_batch(None, owner[0], batch_id)
        return batch_id

    def test_status_ranks_with_one_in_query(self, client, owner, batch):
        body = client.get(f"/api/v1/bulk/{batch}/status", headers=_headers(owner)).json()
        assert [r["overall_score"] for r in body["ranking"]] == [91, 64, 40]

    def test_match_status_reads_the_jd_match_path(self, client, owner, batch):
        res = client.get(f"/api/v1/match/{batch}/status", headers=_headers(owner))
        assert res.status_code == 200, res.text
        assert len(res.json()["ranking"]) == 3

    def test_notify_all_reads_emails_by_json_path_and_records_in_one_write(self, client, owner, db, batch, reports):
        db.table("reports").update({"candidate_notified_decision": None}).eq("user_id", owner[0]).execute()
        with patch("app.services.email.sender.send_raw_email", new=AsyncMock(return_value=True)):
            first = client.post(f"/api/v1/bulk/{batch}/notify-all", headers=_headers(owner), json={"decision": "reject"}).json()
            second = client.post(f"/api/v1/bulk/{batch}/notify-all", headers=_headers(owner), json={"decision": "reject"}).json()
        # Two candidates have an email on file; the formula one does not.
        assert first["emails_sent"] == 2
        assert second["emails_sent"] == 0 and second["already_notified"] == 2

    def test_duplicates_read_full_reports(self, client, owner, batch):
        res = client.get(f"/api/v1/bulk/{batch}/duplicates", headers=_headers(owner))
        assert res.status_code == 200 and res.json()["candidates_compared"] == 3


class TestTeamsAndDiscussionAgainstPostgREST:
    def test_share_comment_vote_and_team_access(self, client, owner, teammate, stranger, reports):
        team = client.post("/api/v1/teams", headers=_headers(owner), json={"name": f"E2E {uuid.uuid4().hex[:6]}"})
        assert team.status_code == 200, team.text
        team_id = team.json()["id"] if "id" in team.json() else team.json()["team"]["id"]

        with patch("app.services.email.sender.send_raw_email", new=AsyncMock(return_value=True)):
            inv = client.post(f"/api/v1/teams/{team_id}/invite", headers=_headers(owner), json={"email": teammate[1]})
        assert inv.status_code == 200, inv.text

        from app.services.teams.access import accept_pending_invites_for_email
        from supabase import create_client

        assert accept_pending_invites_for_email(create_client(URL, KEY), teammate[0], teammate[1]) >= 1

        assert client.post(f"/api/v1/reports/{reports['anita']}/share", headers=_headers(owner), json={"team_id": team_id}).status_code == 200
        as_mate = client.get(f"/api/v1/reports/{reports['anita']}", headers=_headers(teammate))
        assert as_mate.status_code == 200
        assert as_mate.json()["is_owner"] is False
        assert client.get(f"/api/v1/reports/{reports['anita']}", headers=_headers(owner)).json()["is_owner"] is True
        assert client.get(f"/api/v1/reports/{reports['anita']}", headers=_headers(stranger)).status_code == 403

        # The teammate finds it on the team, without being sent the link.
        shared = client.get(f"/api/v1/teams/{team_id}/reports", headers=_headers(teammate))
        assert shared.status_code == 200, shared.text
        assert [r["id"] for r in shared.json()["reports"]] == [reports["anita"]]
        assert shared.json()["reports"][0]["is_mine"] is False
        assert client.get(f"/api/v1/teams/{team_id}/reports", headers=_headers(stranger)).status_code == 403
        # Emailing the candidate and deleting the file stay the owner's.
        assert client.get(f"/api/v1/reports/{reports['anita']}/notify/draft?decision=reject", headers=_headers(teammate)).status_code == 403
        assert client.delete(f"/api/v1/reports/{reports['anita']}", headers=_headers(teammate)).status_code == 403

        c = client.post(f"/api/v1/reports/{reports['anita']}/comments", headers=_headers(teammate), json={"comment": "Looks good"})
        assert c.status_code == 200, c.text
        assert c.json()["user_name"] == "You"
        listed = client.get(f"/api/v1/reports/{reports['anita']}/comments", headers=_headers(owner)).json()["comments"]
        assert [x["comment"] for x in listed] == ["Looks good"]

        for vote in ("advance", "maybe"):  # the second replaces the first
            assert client.post(f"/api/v1/reports/{reports['anita']}/vote", headers=_headers(teammate), json={"vote": vote}).status_code == 200
        tally = client.get(f"/api/v1/reports/{reports['anita']}/votes", headers=_headers(owner)).json()["tally"]
        assert tally == {"advance": 0, "reject": 0, "maybe": 1}

        assert client.delete(f"/api/v1/teams/{team_id}", headers=_headers(owner)).status_code in (200, 204)


class TestSavedJdsAgainstPostgREST:
    def test_save_list_use_delete(self, client, owner):
        text = "We need a senior Python engineer with PostgreSQL and Kubernetes experience."
        saved = client.post("/api/v1/job-descriptions", headers=_headers(owner), json={"name": f"Role {uuid.uuid4().hex[:5]}", "jd_text": text})
        assert saved.status_code in (200, 201), saved.text
        jd_id = saved.json()["job_description"]["id"]
        assert any(j["id"] == jd_id for j in client.get("/api/v1/job-descriptions", headers=_headers(owner)).json()["job_descriptions"])
        assert client.delete(f"/api/v1/job-descriptions/{jd_id}", headers=_headers(owner)).status_code in (200, 204)


class TestBillingAgainstPostgREST:
    def test_usage_is_counted_from_the_ledger(self, client, owner, reports):
        usage = client.get("/api/v1/billing/usage", headers=_headers(owner)).json()
        assert usage["used"] >= 3

    def test_quota_and_plan_change(self, client, owner, stranger, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "FREE_MONTHLY_ANALYSES", 1)
        monkeypatch.setattr(settings, "PRO_MONTHLY_ANALYSES", 10_000)
        monkeypatch.setattr(settings, "ADMIN_EMAILS", owner[1])
        assert client.post("/api/v1/analysis/upload", headers=_headers(owner),
                           files={"file": ("cv.pdf", PDF, "application/pdf")}).status_code == 402
        res = client.post("/api/v1/billing/admin/plan", headers=_headers(owner), json={"email": owner[1], "plan": "pro"})
        assert res.status_code == 200, res.text
        # Upsert: a second change must update the same row, not collide.
        assert client.post("/api/v1/billing/admin/plan", headers=_headers(owner), json={"email": owner[1], "plan": "pro"}).status_code == 200
        assert client.get("/api/v1/billing/usage", headers=_headers(owner)).json()["plan"] == "pro"
        client.post("/api/v1/billing/admin/plan", headers=_headers(owner), json={"email": owner[1], "plan": "free"})

    def test_account_count_comes_from_profiles(self, client, owner, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ADMIN_EMAILS", owner[1])
        assert client.get("/api/v1/auth/stats", headers=_headers(owner)).json()["registered_users"] >= 3


class TestDeletionAgainstPostgREST:
    def test_deleting_a_discussed_report_cascades(self, client, owner, db, reports):
        rid = reports["formula"]
        client.post(f"/api/v1/reports/{rid}/comments", headers=_headers(owner), json={"comment": "x"})
        assert client.delete(f"/api/v1/reports/{rid}", headers=_headers(owner)).status_code == 204
        assert db.table("reports").select("id").eq("id", rid).execute().data == []
        assert db.table("report_comments").select("id").eq("report_id", rid).execute().data == []


class TestSessionsAgainstPostgREST:
    def test_sign_out_everywhere_is_stored_and_enforced(self, client, stranger, db):
        from app.services import sessions

        headers = _headers(stranger)
        assert client.get("/api/v1/billing/usage", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/logout-all", headers=headers).status_code == 200
        rows = db.table("session_revocations").select("user_id,revoked_before").eq("user_id", stranger[0]).execute().data
        assert len(rows) == 1
        # A second revocation updates the same row (upsert on the primary key).
        sessions.clear_cache()
        assert client.post("/api/v1/auth/logout-all", headers=_headers(stranger)).status_code == 200
        assert len(db.table("session_revocations").select("user_id").eq("user_id", stranger[0]).execute().data) == 1
        sessions.clear_cache()
        assert client.get("/api/v1/billing/usage", headers=headers).status_code == 401
        assert client.get("/api/v1/billing/usage", headers=_headers(stranger)).status_code == 200


class TestSchemaCheckAgainstPostgREST:
    """The migration check, against the error shapes a real PostgREST sends."""

    def test_every_migration_is_detected_as_present(self, db):
        from app.core import schema_check

        report = schema_check.check(db)
        assert report.status == "ok", (report.missing, report.errors)

    def test_a_missing_table_and_column_are_classified_as_missing(self, db, monkeypatch):
        from app.core import schema_check

        monkeypatch.setattr(schema_check, "REQUIREMENTS", (
            ("009_future.sql", "no_such_table", ("id",)),
            ("009_future.sql", "reports", ("id", "no_such_column")),
        ))
        report = schema_check.check(db)
        assert report.status == "missing", report.errors
        assert report.missing == {"009_future.sql": ["no_such_table", "reports.no_such_column"]}

    def test_health_reports_the_schema_as_ok(self, client):
        from app.core import schema_check

        schema_check.clear_cache()
        assert client.get("/api/v1/health").json()["services"]["schema"] == "ok"


class TestAccountDeletionAgainstPostgres:
    """
    Deleting an account against the real schema: the foreign keys must
    cascade from auth.users through every table (sql/001-008), saved_jds must
    be removed by the API (it has no foreign key), and the tombstone (009)
    must refuse the account's old tokens.

    No GoTrue runs in this stack, so the one admin call — deleting the
    auth.users row — is done with psql in the Postgres container. Everything
    else goes through the real endpoint and PostgREST.
    """

    @pytest.fixture
    def leaver(self):
        if len(USERS) < 4 or not os.environ.get("HIRELENS_E2E_DB_CONTAINER"):
            pytest.skip("needs a fourth seeded user and HIRELENS_E2E_DB_CONTAINER")
        return USERS[3]

    def test_the_account_and_everything_it_owns_is_deleted(self, client, db, leaver, owner, monkeypatch):
        import subprocess
        from app.services import sessions

        uid, email = leaver
        headers = _headers(leaver)
        rid, _ = _analyse(client, leaver, _report("Leah Candidate", "leah@example.com", ["SQL"]), "leah.pdf")
        team = client.post("/api/v1/teams", json={"name": "Leaver's team"}, headers=headers)
        assert team.status_code == 200, team.text
        team_id = team.json()["id"]
        assert client.post(f"/api/v1/reports/{rid}/share", json={"team_id": team_id}, headers=headers).status_code == 200
        invite = client.post(f"/api/v1/teams/{team_id}/invite", json={"email": "invitee@e2e-example.com"}, headers=headers)
        assert invite.status_code == 200, invite.text
        assert client.post("/api/v1/job-descriptions", json={"name": "Data role", "jd_text": "We need a data engineer " * 5},
                           headers=headers).status_code in (200, 201)
        # Someone else's comment on the leaver's shared report goes too.
        db.table("team_members").insert({"team_id": team_id, "user_id": owner[0], "role": "member"}).execute()
        assert client.post(f"/api/v1/reports/{rid}/comments", json={"comment": "Strong SQL"},
                           headers=_headers(owner)).status_code == 200

        container = os.environ["HIRELENS_E2E_DB_CONTAINER"]

        def delete_auth_user(user_id, should_soft_delete=False):
            subprocess.run(
                ["docker", "exec", container, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-qc",
                 f"delete from auth.users where id = '{uuid.UUID(user_id)}'"],
                check=True, capture_output=True, text=True,
            )

        monkeypatch.setattr(db.auth.admin, "delete_user", delete_auth_user)
        res = client.post("/api/v1/auth/delete-account", json={"confirm_email": email}, headers=headers)
        assert res.status_code == 200, res.text

        def count(table, column, value):
            return len(db.table(table).select(column).eq(column, value).execute().data)

        assert count("reports", "user_id", uid) == 0
        assert count("report_comments", "report_id", rid) == 0
        assert count("teams", "owner_id", uid) == 0
        assert count("team_members", "team_id", team_id) == 0
        assert count("team_invites", "team_id", team_id) == 0
        assert count("saved_jds", "user_id", uid) == 0
        assert count("usage_events", "user_id", uid) == 0
        assert count("profiles", "id", uid) == 0
        assert count("deleted_accounts", "user_id", uid) == 1
        # The owner's own account is untouched.
        assert count("profiles", "id", owner[0]) == 1

        sessions.clear_cache()
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        assert client.get("/api/v1/auth/me", headers=_headers(owner)).status_code == 200


class TestOperatorScreenAgainstPostgREST:
    def test_search_plans_and_detail(self, client, owner, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ADMIN_EMAILS", owner[1])
        headers = _headers(owner)
        rows = client.get("/api/v1/billing/admin/accounts", params={"q": "e2e-example"}, headers=headers)
        assert rows.status_code == 200, rows.text
        assert owner[1] in {r["email"] for r in rows.json()["accounts"]}
        # "_" is literal: as a wildcard, "owner_" would match "owner@...".
        literal = client.get("/api/v1/billing/admin/accounts", params={"q": "owner_"}, headers=headers)
        assert literal.json()["accounts"] == []
        detail = client.get("/api/v1/billing/admin/account", params={"email": owner[1]}, headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["user_id"] == owner[0]
        assert "usage" in detail.json()


class TestUpiPaymentsAgainstPostgREST:
    def test_claim_approve_and_the_database_rules(self, client, db, owner, teammate, monkeypatch):
        from app.core.config import settings
        from app.services import sessions

        sessions.clear_cache()
        monkeypatch.setattr(settings, "ADMIN_EMAILS", owner[1])
        monkeypatch.setattr(settings, "PAYMENT_UPI_ID", "hirelens@okbank")
        monkeypatch.setattr(settings, "PRO_PRICE_INR", 499)
        monkeypatch.setattr(settings, "UPGRADE_URL", "")
        ref = str(uuid.uuid4().int)[:12]

        claim = client.post("/api/v1/billing/payments", json={"plan": "pro", "reference": ref}, headers=_headers(teammate))
        assert claim.status_code == 201, claim.text
        pid = claim.json()["id"]

        # The partial unique indexes from sql/010, hit directly: a second
        # pending claim for the account, and a second live claim on the
        # reference, are both refused by Postgres itself.
        with pytest.raises(Exception) as second_pending:
            db.table("payment_requests").insert({
                "user_id": teammate[0], "plan": "pro", "amount_inr": 499, "reference": "999999999999",
            }).execute()
        assert "23505" in str(second_pending.value) or "duplicate" in str(second_pending.value).lower()
        reused = client.post("/api/v1/billing/payments", json={"plan": "pro", "reference": ref}, headers=_headers(owner))
        assert reused.status_code == 409

        approved = client.post(f"/api/v1/billing/admin/payments/{pid}/approve", headers=_headers(owner))
        assert approved.status_code == 200, approved.text
        row = db.table("payment_requests").select("status,decided_by").eq("id", pid).execute().data[0]
        assert row == {"status": "approved", "decided_by": owner[1]}
        sub = db.table("subscriptions").select("plan,current_period_end,provider").eq("user_id", teammate[0]).execute().data[0]
        assert sub["plan"] == "pro" and sub["provider"] == "upi" and sub["current_period_end"]
        usage = client.get("/api/v1/billing/usage", headers=_headers(teammate)).json()
        assert usage["plan"] == "pro" and usage["plan_expires_at"]
        assert client.post(f"/api/v1/billing/admin/payments/{pid}/approve", headers=_headers(owner)).status_code == 409
