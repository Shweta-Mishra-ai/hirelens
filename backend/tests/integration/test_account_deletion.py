"""
Self-serve account deletion: everything the account owns goes, nothing that
belongs to anyone else does, and the account's existing sessions stop working
at once — on the local store and on the Supabase path.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core import local_db
from app.core.dependencies import get_db
from app.core.security import create_access_token
from app.main import app
from app.services import sessions
from tests.fake_supabase import FakeSupabase, FakeUser

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_sessions():
    sessions.clear_cache()
    yield
    sessions.clear_cache()
    app.dependency_overrides.pop(get_db, None)


def _signup(email=None, password="Password123!"):
    email = email or f"del_{uuid.uuid4().hex[:8]}@example.com"
    res = client.post("/api/v1/auth/signup", json={"email": email, "password": password, "full_name": "Del Eter"})
    assert res.status_code == 200, res.text
    body = res.json()
    return {
        "id": body["user"]["id"],
        "email": email,
        "password": password,
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }


def _delete(user, confirm=None):
    return client.post(
        "/api/v1/auth/delete-account",
        json={"confirm_email": confirm if confirm is not None else user["email"]},
        headers=user["headers"],
    )


def _local_rows(table, column, value):
    with local_db._get_connection() as conn:
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (value,)).fetchone()[0]
        except Exception:
            return 0


class TestLocalStore:
    def test_everything_the_account_owns_is_removed(self):
        user = _signup()
        other = _signup()
        rid = str(uuid.uuid4())
        local_db.save_report(rid, user["id"], "cv.pdf", "Priya", 70, "manual_review", {"candidate": {"name": "Priya"}})
        other_rid = str(uuid.uuid4())
        local_db.save_report(other_rid, other["id"], "cv.pdf", "Omar", 60, "manual_review", {"candidate": {"name": "Omar"}})
        local_db.save_jd(str(uuid.uuid4()), user["id"], "Backend", "We need a backend engineer " * 5)
        local_db.add_comment(rid, other["id"], "a comment by someone else on this report")
        local_db.add_comment(other_rid, user["id"], "this user's comment on another report")

        res = _delete(user)
        assert res.status_code == 200, res.text

        assert _local_rows("users", "id", user["id"]) == 0
        assert _local_rows("reports", "user_id", user["id"]) == 0
        assert _local_rows("saved_jds", "user_id", user["id"]) == 0
        assert _local_rows("report_comments", "report_id", rid) == 0
        assert _local_rows("report_comments", "user_id", user["id"]) == 0
        # The other account is untouched.
        assert _local_rows("users", "id", other["id"]) == 1
        assert _local_rows("reports", "id", other_rid) == 1

    def test_the_accounts_sessions_stop_working_immediately(self):
        user = _signup()
        assert _delete(user).status_code == 200
        assert client.get("/api/v1/auth/me", headers=user["headers"]).status_code == 401
        # And after the in-process cache is gone, from the stored revocation.
        sessions.clear_cache()
        assert client.get("/api/v1/auth/me", headers=user["headers"]).status_code == 401

    def test_the_old_password_no_longer_signs_in(self):
        user = _signup()
        assert _delete(user).status_code == 200
        res = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
        assert res.status_code == 401

    def test_the_email_can_sign_up_again_as_a_new_empty_account(self):
        user = _signup()
        local_db.save_report(str(uuid.uuid4()), user["id"], "cv.pdf", "Priya", 70, "manual_review", {})
        assert _delete(user).status_code == 200
        again = _signup(email=user["email"])
        assert again["id"] != user["id"]
        listed = client.get("/api/v1/reports", headers=again["headers"]).json()
        assert listed.get("total", len(listed.get("reports", []))) == 0

    def test_a_wrong_confirmation_deletes_nothing(self):
        user = _signup()
        res = _delete(user, confirm="someone-else@example.com")
        assert res.status_code == 422
        assert _local_rows("users", "id", user["id"]) == 1
        assert client.get("/api/v1/auth/me", headers=user["headers"]).status_code == 200

    def test_confirmation_ignores_case_and_spaces(self):
        user = _signup()
        assert _delete(user, confirm=f"  {user['email'].upper()} ").status_code == 200

    def test_refused_while_an_analysis_is_running(self):
        from app.api.v1.endpoints.analysis import _jobs

        user = _signup()
        job_id = str(uuid.uuid4())
        _jobs[job_id] = {"status": "running", "user_id": user["id"]}
        try:
            res = _delete(user)
            assert res.status_code == 409
            assert "still running" in res.json()["message"]
            assert _local_rows("users", "id", user["id"]) == 1
        finally:
            _jobs.pop(job_id, None)

    def test_cached_reports_are_dropped_from_memory(self):
        from app.api.v1.endpoints.analysis import _jobs

        user = _signup()
        _jobs["report_cached"] = {"user_id": user["id"], "candidate": {"name": "X"}}
        assert _delete(user).status_code == 200
        assert _jobs.get("report_cached") is None

    def test_requires_a_signed_in_user(self):
        res = client.post("/api/v1/auth/delete-account", json={"confirm_email": "x@example.com"})
        assert res.status_code == 401


class TestSupabasePath:
    def _setup(self):
        uid, other_id = str(uuid.uuid4()), str(uuid.uuid4())
        email = f"sb_{uuid.uuid4().hex[:8]}@example.com"
        own_team, other_team = str(uuid.uuid4()), str(uuid.uuid4())
        rid, other_rid = str(uuid.uuid4()), str(uuid.uuid4())
        fake = FakeSupabase({
            "profiles": [{"id": uid, "email": email}, {"id": other_id, "email": "o@example.com"}],
            "reports": [
                {"id": rid, "user_id": uid, "team_id": own_team, "report_data": {}},
                {"id": other_rid, "user_id": other_id, "team_id": own_team, "report_data": {}},
            ],
            "teams": [
                {"id": own_team, "name": "Mine", "owner_id": uid},
                {"id": other_team, "name": "Theirs", "owner_id": other_id},
            ],
            "team_members": [
                {"team_id": own_team, "user_id": uid, "role": "owner"},
                {"team_id": own_team, "user_id": other_id, "role": "member"},
                {"team_id": other_team, "user_id": other_id, "role": "owner"},
                {"team_id": other_team, "user_id": uid, "role": "member"},
            ],
            "team_invites": [{"id": str(uuid.uuid4()), "team_id": other_team, "email": "x@example.com", "invited_by": uid}],
            "report_comments": [
                {"id": str(uuid.uuid4()), "report_id": rid, "user_id": other_id, "comment": "on theirs"},
                {"id": str(uuid.uuid4()), "report_id": other_rid, "user_id": uid, "comment": "by them"},
            ],
            "saved_jds": [
                {"id": str(uuid.uuid4()), "user_id": uid, "name": "JD", "jd_text": "x"},
                {"id": str(uuid.uuid4()), "user_id": other_id, "name": "JD", "jd_text": "y"},
            ],
            "subscriptions": [{"user_id": uid, "plan": "pro"}],
            "usage_events": [{"id": str(uuid.uuid4()), "user_id": uid, "kind": "analysis"}],
            "deleted_accounts": [],
            "session_revocations": [],
        })
        fake.auth.users[email] = ("pw", FakeUser(uid, email))
        fake.auth.users["o@example.com"] = ("pw", FakeUser(other_id, "o@example.com"))
        app.dependency_overrides[get_db] = lambda: fake
        user = {
            "id": uid, "email": email,
            "headers": {"Authorization": f"Bearer {create_access_token({'sub': uid, 'email': email})}"},
        }
        return fake, user, {"other_id": other_id, "own_team": own_team, "other_team": other_team,
                            "rid": rid, "other_rid": other_rid}

    def test_the_account_and_its_data_go_and_others_data_stays(self):
        fake, user, ids = self._setup()
        res = _delete(user)
        assert res.status_code == 200, res.text
        t = fake.tables
        uid = user["id"]

        assert uid in fake.auth.admin.deleted
        assert [r["user_id"] for r in t["saved_jds"]] == [ids["other_id"]]
        assert all(r["user_id"] != uid for r in t["reports"])
        assert all(r["id"] != ids["own_team"] for r in t["teams"])
        assert all(r.get("user_id") != uid for r in t["subscriptions"] + t["usage_events"])
        assert [r["user_id"] for r in t["deleted_accounts"]] == [uid]
        # The other account keeps its own report (unshared from the deleted
        # team), its own team, and its membership there.
        other_report = next(r for r in t["reports"] if r["id"] == ids["other_rid"])
        assert other_report["team_id"] is None
        assert any(r["id"] == ids["other_team"] for r in t["teams"])
        assert {"team_id": ids["other_team"], "user_id": ids["other_id"], "role": "owner"} in t["team_members"]
        assert all(r.get("user_id") != uid for r in t["team_members"])
        assert t["team_invites"][0]["invited_by"] is None

    def test_old_tokens_are_refused_from_the_stored_tombstone(self):
        fake, user, _ = self._setup()
        assert _delete(user).status_code == 200
        sessions.clear_cache()  # as another process, or after a restart, would see it
        assert client.get("/api/v1/auth/me", headers=user["headers"]).status_code == 401

    def test_without_migration_009_nothing_is_deleted(self):
        fake, user, _ = self._setup()
        fake.fail("deleted_accounts", "select")
        res = _delete(user)
        assert res.status_code == 503
        assert res.json()["error"] == "account_deletion_unavailable"
        assert getattr(fake.auth.admin, "deleted", []) == []
        assert len(fake.tables["saved_jds"]) == 2
        assert len(fake.tables["reports"]) == 2

    def test_a_failed_auth_delete_is_reported_and_leaves_the_account_usable(self):
        from tests.fake_supabase import AuthApiError

        fake, user, _ = self._setup()
        fake.auth.raises = AuthApiError("database error", status=500)
        res = _delete(user)
        assert res.status_code == 503
        assert "everything else is unchanged" in res.json()["message"]
        assert fake.tables["deleted_accounts"] == []
        assert len(fake.tables["reports"]) == 2
        sessions.clear_cache()
        fake.auth.raises = None
        assert client.get("/api/v1/auth/me", headers=user["headers"]).status_code == 200


class TestDeletedLookup:
    """Only a real row in deleted_accounts may sign someone out."""

    def _db(self, data):
        from unittest.mock import MagicMock

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = data
        return db

    def test_a_row_means_deleted(self):
        assert sessions._is_deleted(self._db([{"user_id": "u"}]), "u") is True

    @pytest.mark.parametrize("data", [[], None, {"user_id": "u"}, "u"])
    def test_anything_else_does_not(self, data):
        assert sessions._is_deleted(self._db(data), "u") is False

    def test_a_truthy_non_list_from_an_unexpected_client_does_not(self):
        from unittest.mock import MagicMock

        db = MagicMock()  # every attribute truthy, as with a generic mock
        assert sessions._is_deleted(db, "u") is False
