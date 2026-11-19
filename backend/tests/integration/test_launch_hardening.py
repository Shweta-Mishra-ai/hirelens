"""
Regression tests for the pre-launch hardening pass.

Each class pins one defect that was found and fixed, named for what a
customer would have experienced. Supabase-path tests inject the fake client
through get_db, exactly as tests/integration/test_reports_db_path.py does.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import analysis as analysis_ep
from app.core.config import settings
from app.core.dependencies import get_db
from app.main import app
from tests.fake_supabase import FakeSupabase

client = TestClient(app)

PDF = b"%PDF-1.4\n" + b"0" * 2048
RESUME_TEXT = (
    "Anita Rao\nanita@example.com\nExperience\nSenior Engineer at Acme 2019-2024\n"
    "Education\nB.Tech Computer Science\nSkills\nPython, Go, PostgreSQL\n" * 3
)


def _report(name="Anita Rao", email="anita@example.com", score=80):
    return {
        "candidate": {"name": name, "email": email},
        "credibility": {"overall": score, "recommendation": "recommended"},
        "skills": {"all_claimed": ["Python"]},
        "flags": [],
    }


def _account(email):
    creds = {"email": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "Launch Tester"})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    body = res.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user_id": body["user"]["id"],
        "email": email,
    }


@pytest.fixture
def account():
    return _account("launch_hardening@example.com")


@pytest.fixture
def fake_db():
    fake = FakeSupabase({"reports": [], "team_members": [], "profiles": []})
    app.dependency_overrides[get_db] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def mocked_pipeline():
    """The parser and the model, replaced, so an upload runs end to end."""
    with patch.object(analysis_ep, "extract_text", return_value=RESUME_TEXT), \
         patch.object(analysis_ep, "looks_like_resume", return_value=(True, None)), \
         patch.object(analysis_ep.engine, "run", new=AsyncMock(side_effect=lambda **_: _report())):
        yield


def _upload(headers):
    return client.post(
        "/api/v1/analysis/upload",
        headers=headers,
        files={"file": ("cv.pdf", PDF, "application/pdf")},
    )


# ── Plans and quotas ─────────────────────────────────────────────────────────

class TestMonthlyQuota:
    def test_quotas_are_off_by_default(self, account, mocked_pipeline):
        assert settings.FREE_MONTHLY_ANALYSES == 0
        for _ in range(3):
            assert _upload(account["headers"]).status_code == 200

    def test_an_upload_past_the_quota_is_refused_with_402(self, account, mocked_pipeline, monkeypatch):
        monkeypatch.setattr(settings, "FREE_MONTHLY_ANALYSES", 2)
        monkeypatch.setattr(settings, "UPGRADE_URL", "https://pay.example.com/pro")
        user = _account("quota_user@example.com")
        assert _upload(user["headers"]).status_code == 200
        assert _upload(user["headers"]).status_code == 200

        res = _upload(user["headers"])
        assert res.status_code == 402
        body = res.json()
        assert body["error"] == "quota_exceeded"
        assert body["limit"] == 2
        assert body["remaining"] == 0
        assert body["upgrade_url"] == "https://pay.example.com/pro"

    def test_a_failed_analysis_is_never_charged(self, mocked_pipeline, monkeypatch):
        monkeypatch.setattr(settings, "FREE_MONTHLY_ANALYSES", 1)
        user = _account("quota_failure@example.com")
        with patch.object(analysis_ep.engine, "run", new=AsyncMock(side_effect=RuntimeError("provider down"))):
            assert _upload(user["headers"]).status_code == 200  # accepted; fails in the background
        usage = client.get("/api/v1/billing/usage", headers=user["headers"]).json()
        assert usage["used"] == 0
        # ...so the one analysis the plan includes is still available.
        assert _upload(user["headers"]).status_code == 200

    def test_a_batch_bigger_than_what_is_left_is_refused_whole(self, monkeypatch):
        monkeypatch.setattr(settings, "FREE_MONTHLY_ANALYSES", 2)
        user = _account("quota_batch@example.com")
        files = [("files", (f"cv{i}.pdf", PDF, "application/pdf")) for i in range(3)]
        res = client.post("/api/v1/bulk/upload", headers=user["headers"], files=files)
        assert res.status_code == 402
        assert "3 resumes" in res.json()["message"]

    def test_deleting_reports_does_not_give_quota_back(self, mocked_pipeline, monkeypatch):
        monkeypatch.setattr(settings, "FREE_MONTHLY_ANALYSES", 1)
        user = _account("quota_delete@example.com")
        job = _upload(user["headers"]).json()["job_id"]
        report_id = client.get(f"/api/v1/analysis/{job}/status", headers=user["headers"]).json()["report_id"]
        assert client.delete(f"/api/v1/reports/{report_id}", headers=user["headers"]).status_code == 204
        assert _upload(user["headers"]).status_code == 402

    def test_usage_is_reported_to_the_account(self, mocked_pipeline, monkeypatch):
        monkeypatch.setattr(settings, "FREE_MONTHLY_ANALYSES", 5)
        user = _account("quota_usage@example.com")
        _upload(user["headers"])
        usage = client.get("/api/v1/billing/usage", headers=user["headers"]).json()
        assert usage["plan"] == "free"
        assert usage["used"] == 1
        assert usage["limit"] == 5
        assert usage["remaining"] == 4
        assert usage["unlimited"] is False

    def test_an_upgraded_account_gets_the_bigger_quota(self, mocked_pipeline, monkeypatch):
        monkeypatch.setattr(settings, "FREE_MONTHLY_ANALYSES", 1)
        monkeypatch.setattr(settings, "PRO_MONTHLY_ANALYSES", 3)
        user = _account("quota_pro@example.com")
        admin = _account("quota_admin@example.com")
        monkeypatch.setattr(settings, "ADMIN_EMAILS", admin["email"])
        res = client.post(
            "/api/v1/billing/admin/plan",
            headers=admin["headers"],
            json={"email": user["email"], "plan": "pro"},
        )
        assert res.status_code == 200, res.text
        for _ in range(3):
            assert _upload(user["headers"]).status_code == 200
        assert _upload(user["headers"]).status_code == 402

    def test_a_customer_cannot_change_their_own_plan(self, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "someone-else@example.com")
        user = _account("quota_self_upgrade@example.com")
        res = client.post(
            "/api/v1/billing/admin/plan",
            headers=user["headers"],
            json={"email": user["email"], "plan": "team"},
        )
        assert res.status_code == 403

    def test_usage_is_metered_in_supabase_when_configured(self, account, fake_db, mocked_pipeline):
        _upload(account["headers"])
        events = fake_db.tables.get("usage_events", [])
        assert len(events) == 1
        assert events[0]["user_id"] == account["user_id"]
        assert events[0]["kind"] == "analysis"


# ── Operator-only endpoints ──────────────────────────────────────────────────

class TestOperatorEndpoints:
    def test_diagnostics_are_closed_in_production_until_admins_are_named(self, account, monkeypatch):
        monkeypatch.setattr(settings, "APP_ENV", "production")
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        assert client.get("/api/v1/health/diagnostics", headers=account["headers"]).status_code == 403
        assert client.get("/api/v1/auth/stats", headers=account["headers"]).status_code == 403

    def test_a_named_admin_gets_diagnostics(self, account, monkeypatch):
        monkeypatch.setattr(settings, "APP_ENV", "production")
        monkeypatch.setattr(settings, "ADMIN_EMAILS", account["email"].upper())
        assert client.get("/api/v1/health/diagnostics", headers=account["headers"]).status_code == 200

    def test_any_other_signed_in_user_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@example.com")
        other = _account("not_an_admin@example.com")
        assert client.get("/api/v1/health/diagnostics", headers=other["headers"]).status_code == 403

    def test_stats_count_accounts_not_reports(self, account, fake_db, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", account["email"])
        fake_db.tables["profiles"] = [{"id": f"u{i}", "email": f"{i}@x.com"} for i in range(4)]
        fake_db.tables["reports"] = [{"id": f"r{i}", "user_id": "u1"} for i in range(40)]
        body = client.get("/api/v1/auth/stats", headers=account["headers"]).json()
        assert body["registered_users"] == 4


# ── Request size ─────────────────────────────────────────────────────────────

class TestBodySizeLimit:
    def test_an_oversized_declared_body_is_refused_before_it_is_read(self, account):
        too_big = settings.MAX_FILE_SIZE_MB * 1024 * 1024 + 3 * 1024 * 1024
        res = client.post(
            "/api/v1/analysis/upload",
            headers={**account["headers"], "Content-Length": str(too_big), "Content-Type": "multipart/form-data; boundary=x"},
            content=b"--x--",
        )
        assert res.status_code == 413
        assert res.json()["error"] == "payload_too_large"

    def test_an_undeclared_streamed_body_is_cut_off_at_the_limit(self, account, monkeypatch):
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)

        def chunks():
            # A well-formed multipart body with no Content-Length, so only the
            # streamed byte count can stop it (4.5MB against a 3MB cap).
            yield (
                b"--x\r\nContent-Disposition: form-data; name=\"file\"; "
                b"filename=\"cv.pdf\"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4\n"
            )
            for _ in range(9):
                yield b"0" * (512 * 1024)
            yield b"\r\n--x--\r\n"

        res = client.post(
            "/api/v1/analysis/upload",
            headers={**account["headers"], "Content-Type": "multipart/form-data; boundary=x"},
            content=chunks(),
        )
        assert res.status_code == 413

    def test_ordinary_json_requests_are_unaffected(self, account):
        assert client.get("/api/v1/reports", headers=account["headers"]).status_code == 200


# ── Silent failures on the Supabase path ─────────────────────────────────────

def _row(rid, uid, name="Anita Rao", **extra):
    row = {
        "id": rid, "user_id": uid, "file_name": f"{rid}.pdf", "candidate_name": name,
        "overall_score": 70, "recommendation": "recommended", "recruiter_decision": None,
        "created_at": "2026-11-01T00:00:00+00:00", "team_id": None,
        "report_data": _report(name),
    }
    row.update(extra)
    return row


class TestNoFalseSuccess:
    def test_a_failed_supabase_delete_is_not_reported_as_deleted(self, account, fake_db):
        fake_db.tables["reports"] = [_row("r1", account["user_id"])]
        fake_db.fail("reports", "delete")
        res = client.delete("/api/v1/reports/r1", headers=account["headers"])
        assert res.status_code == 503
        assert len(fake_db.tables["reports"]) == 1

    def test_a_database_outage_is_not_reported_as_report_not_found(self, account, fake_db):
        fake_db.fail("reports", "select")
        res = client.get("/api/v1/reports/r1", headers=account["headers"])
        assert res.status_code == 503
        assert res.json()["error"] == "database_unavailable"

    def test_an_undelivered_email_is_not_recorded_as_a_notification(self, account, fake_db):
        fake_db.tables["reports"] = [_row("r1", account["user_id"])]
        with patch("app.services.email.sender.send_raw_email", new=AsyncMock(return_value=False)):
            res = client.post(
                "/api/v1/reports/r1/notify",
                headers=account["headers"],
                json={"decision": "advance", "subject": "Hello", "body": "Next steps"},
            )
        assert res.status_code == 200
        assert res.json()["email_sent"] is False
        assert res.json()["status"] == "not_sent"
        assert fake_db.tables["reports"][0].get("candidate_notified_at") is None

    def test_a_delivered_email_is_recorded_with_a_real_timestamp(self, account, fake_db):
        fake_db.tables["reports"] = [_row("r1", account["user_id"])]
        with patch("app.services.email.sender.send_raw_email", new=AsyncMock(return_value=True)):
            client.post(
                "/api/v1/reports/r1/notify",
                headers=account["headers"],
                json={"decision": "advance", "subject": "Hello", "body": "Next steps"},
            )
        stamped = fake_db.tables["reports"][0]["candidate_notified_at"]
        assert stamped and stamped != "now()" and stamped.startswith("20")


# ── CSV formula injection ────────────────────────────────────────────────────

class TestCsvFormulaInjection:
    def test_a_resume_named_like_a_formula_is_exported_as_text(self, account, fake_db):
        evil = '=HYPERLINK("https://evil.example","Open")'
        fake_db.tables["reports"] = [_row("r1", account["user_id"], name=evil)]
        res = client.get("/api/v1/reports/export.csv", headers=account["headers"])
        assert res.status_code == 200
        assert "'=HYPERLINK" in res.text
        assert "\n=HYPERLINK" not in res.text and ",=HYPERLINK" not in res.text


# ── International names ──────────────────────────────────────────────────────

class TestUnicodeSearch:
    def test_accented_names_survive_sanitisation(self):
        from app.api.v1.endpoints.reports import _sanitize_search

        assert _sanitize_search("José") == "José"
        assert _sanitize_search("Müller") == "Müller"
        # PostgREST filter syntax still cannot get through.
        assert _sanitize_search("a,b(c):d*") == "abcd"

    def test_an_accented_search_finds_the_candidate(self, account, fake_db):
        fake_db.tables["reports"] = [
            _row("r1", account["user_id"], name="José Álvarez"),
            _row("r2", account["user_id"], name="Jos Smith"),
        ]
        res = client.get("/api/v1/reports?search=José", headers=account["headers"])
        names = [r["candidate_name"] for r in res.json()["reports"]]
        assert names == ["José Álvarez"]


# ── Bulk notify ──────────────────────────────────────────────────────────────

class TestBulkNotifyIsIdempotent:
    def _batch(self, account, fake_db):
        from app.services.queue import batch_store

        uid = account["user_id"]
        fake_db.tables["reports"] = [_row("r1", uid), _row("r2", uid, name="Bharat Shah")]
        for jid, rid in (("j1", "r1"), ("j2", "r2")):
            analysis_ep._jobs[jid] = {
                "id": jid, "user_id": uid, "status": "complete", "stage": "complete",
                "progress": 100, "file_name": f"{rid}.pdf", "report_id": rid, "error": None,
            }
        batch_store.create_batch(None, "bn-idem", uid, ["j1", "j2"], total=2)
        batch_store.release_batch(None, uid, "bn-idem")

    def test_a_second_click_does_not_email_everyone_again(self, account, fake_db):
        self._batch(account, fake_db)
        sent = AsyncMock(return_value=True)
        with patch("app.services.email.sender.send_raw_email", new=sent):
            first = client.post("/api/v1/bulk/bn-idem/notify-all", headers=account["headers"], json={"decision": "reject"})
            second = client.post("/api/v1/bulk/bn-idem/notify-all", headers=account["headers"], json={"decision": "reject"})
        assert first.json()["emails_sent"] == 2
        assert second.json()["emails_sent"] == 0
        assert second.json()["already_notified"] == 2
        assert sent.await_count == 2

    def test_resend_is_an_explicit_choice(self, account, fake_db):
        self._batch(account, fake_db)
        with patch("app.services.email.sender.send_raw_email", new=AsyncMock(return_value=True)):
            client.post("/api/v1/bulk/bn-idem/notify-all", headers=account["headers"], json={"decision": "reject"})
            again = client.post(
                "/api/v1/bulk/bn-idem/notify-all",
                headers=account["headers"],
                json={"decision": "reject", "resend": True},
            )
        assert again.json()["emails_sent"] == 2

    def test_status_polling_costs_one_query_not_one_per_candidate(self, account, fake_db):
        self._batch(account, fake_db)
        fake_db.calls.clear()
        res = client.get("/api/v1/bulk/bn-idem/status", headers=account["headers"])
        assert res.status_code == 200
        assert len(res.json()["ranking"]) == 2
        assert fake_db.calls.count(("reports", "select")) == 1


# ── The event loop ───────────────────────────────────────────────────────────

class _SlowDB(FakeSupabase):
    """Every query takes 300ms, the way a distant database does."""

    def table(self, name):
        query = super().table(name)
        real = query.execute

        def slow():
            time.sleep(0.3)
            return real()

        query.execute = slow
        return query


class TestEventLoopIsNotBlocked:
    @pytest.mark.asyncio
    async def test_slow_database_reads_run_concurrently(self, account):
        """
        The Supabase client is synchronous. Called from an `async def` route
        it held the event loop for the whole round trip, so with one worker
        the server answered one database-backed request at a time.
        """
        slow = _SlowDB({"reports": [], "team_members": []})
        app.dependency_overrides[get_db] = lambda: slow
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                started = time.monotonic()
                results = await asyncio.gather(*(
                    ac.get("/api/v1/reports", headers=account["headers"]) for _ in range(4)
                ))
                elapsed = time.monotonic() - started
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert all(r.status_code == 200 for r in results)
        # Each request makes two queries (page + count): 0.6s apiece. Run one
        # after another, four would take 2.4s.
        assert elapsed < 1.6, f"requests were serialised: {elapsed:.2f}s"


# ── Session revocation ───────────────────────────────────────────────────────

class TestSessionRevocation:
    def test_sign_out_everywhere_ends_existing_sessions(self):
        user = _account("revoke_everywhere@example.com")
        assert client.get("/api/v1/reports", headers=user["headers"]).status_code == 200
        res = client.post("/api/v1/auth/logout-all", headers=user["headers"])
        assert res.status_code == 200, res.text
        assert client.get("/api/v1/reports", headers=user["headers"]).status_code == 401

    def test_a_new_sign_in_after_signing_out_everywhere_works(self):
        user = _account("revoke_then_login@example.com")
        client.post("/api/v1/auth/logout-all", headers=user["headers"])
        res = client.post("/api/v1/auth/login", json={"email": user["email"], "password": "Password123!"})
        fresh = {"Authorization": f"Bearer {res.json()['access_token']}"}
        assert client.get("/api/v1/reports", headers=fresh).status_code == 200

    def test_a_password_reset_ends_the_old_sessions(self):
        from app.core import local_db

        user = _account("revoke_on_reset@example.com")
        token = "reset-token-for-revocation-test"
        assert local_db.create_password_reset(user["user_id"], token, 600)
        res = client.post("/api/v1/auth/reset-password", json={"access_token": token, "new_password": "NewPassword456!"})
        assert res.status_code == 200, res.text
        assert client.get("/api/v1/reports", headers=user["headers"]).status_code == 401

    def test_other_users_are_unaffected(self):
        a = _account("revoke_a@example.com")
        b = _account("revoke_b@example.com")
        client.post("/api/v1/auth/logout-all", headers=a["headers"])
        assert client.get("/api/v1/reports", headers=b["headers"]).status_code == 200

    def test_a_failed_lookup_does_not_sign_everyone_out(self, monkeypatch):
        from app.core import local_db

        user = _account("revoke_lookup_down@example.com")

        def boom(_):
            raise RuntimeError("database is down")

        monkeypatch.setattr(local_db, "get_revoked_before", boom)
        assert client.get("/api/v1/reports", headers=user["headers"]).status_code == 200

    def test_revocation_works_on_the_supabase_path(self, fake_db):
        from app.core.security import create_access_token
        from app.services import sessions

        uid = "supabase-user-1"
        headers = {"Authorization": f"Bearer {create_access_token({'sub': uid, 'email': 's@example.com'})}"}
        assert client.get("/api/v1/billing/usage", headers=headers).status_code == 200
        sessions.revoke_all(fake_db, uid)
        sessions.clear_cache()
        assert fake_db.tables["session_revocations"][0]["user_id"] == uid
        # The token from before the revocation is refused; one minted after
        # it — even within the same second — is accepted.
        assert client.get("/api/v1/billing/usage", headers=headers).status_code == 401
        fresh = {"Authorization": f"Bearer {create_access_token({'sub': uid, 'email': 's@example.com'})}"}
        assert client.get("/api/v1/billing/usage", headers=fresh).status_code == 200


class TestRateLimiterUnderConcurrency:
    def test_parallel_attempts_cannot_exceed_the_limit(self):
        from concurrent.futures import ThreadPoolExecutor
        from app.core.rate_limit import check_rate_limit
        from app.core.exceptions import RateLimitExceeded

        allowed = []

        def attempt(_):
            try:
                check_rate_limit(None, "parallel-key", 10, window_seconds=60)
                allowed.append(1)
            except RateLimitExceeded:
                pass

        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(attempt, range(200)))
        assert len(allowed) == 10
