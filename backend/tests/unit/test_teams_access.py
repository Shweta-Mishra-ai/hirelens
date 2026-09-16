"""
HireLens — Team Access Control Unit Tests
Run: cd backend && python -m pytest tests/unit/test_teams_access.py -v

Uses a small fake Supabase client that mimics the fluent query-builder API
(.table().select().eq().maybe_single().execute(), etc.) closely enough to
exercise the REAL functions in app/services/teams/access.py end to end,
rather than testing a simplified reimplementation.
"""
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest

from app.services.teams.access import (
    get_user_role, is_team_member, can_manage_team,
    user_can_access_report, accept_pending_invites_for_email,
)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, store: dict, table_name: str):
        self._store = store
        self._table = table_name
        self._filters = []
        self._single = False
        self._op = None
        self._payload = None
        self._on_conflict = None

    def select(self, *_a, **_kw):
        self._op = self._op or "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def in_(self, col, vals):
        self._filters.append((col, set(vals)))
        return self

    def order(self, *_a, **_kw):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def _matches(self, row):
        for col, val in self._filters:
            if isinstance(val, set):
                if row.get(col) not in val:
                    return False
            elif row.get(col) != val:
                return False
        return True

    def execute(self):
        rows = self._store.setdefault(self._table, [])

        if self._op in ("select", None):
            matched = [r for r in rows if self._matches(r)]
            if self._single:
                return FakeResult(matched[0] if matched else None)
            return FakeResult(matched)

        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for p in payload:
                row = {**p}
                row.setdefault("id", str(uuid.uuid4()))
                rows.append(row)
                inserted.append(row)
            return FakeResult(inserted)

        if self._op == "update":
            updated = []
            for r in rows:
                if self._matches(r):
                    r.update(self._payload)
                    updated.append(r)
            return FakeResult(updated)

        if self._op == "delete":
            remaining = [r for r in rows if not self._matches(r)]
            removed_count = len(rows) - len(remaining)
            self._store[self._table] = remaining
            return FakeResult([{"deleted": True}] * removed_count)

        if self._op == "upsert":
            conflict_cols = (self._on_conflict or "").split(",")
            for r in rows:
                if all(r.get(c) == self._payload.get(c) for c in conflict_cols if c):
                    r.update(self._payload)
                    return FakeResult([r])
            row = {**self._payload}
            row.setdefault("id", str(uuid.uuid4()))
            rows.append(row)
            return FakeResult([row])

        return FakeResult(None)


class FakeSupabase:
    def __init__(self):
        self._store: dict[str, list[dict]] = {}

    def table(self, name):
        return FakeQuery(self._store, name)

    def seed(self, table, rows):
        self._store.setdefault(table, []).extend(rows)


class TestGetUserRole:
    def setup_method(self):
        self.db = FakeSupabase()
        self.db.seed("team_members", [
            {"team_id": "t1", "user_id": "u1", "role": "owner"},
            {"team_id": "t1", "user_id": "u2", "role": "member"},
        ])

    def test_returns_role_for_member(self):
        assert get_user_role(self.db, "t1", "u1") == "owner"
        assert get_user_role(self.db, "t1", "u2") == "member"

    def test_returns_none_for_non_member(self):
        assert get_user_role(self.db, "t1", "u-stranger") is None

    def test_returns_none_when_no_db(self):
        assert get_user_role(None, "t1", "u1") is None


class TestIsTeamMemberAndCanManage:
    def setup_method(self):
        self.db = FakeSupabase()
        self.db.seed("team_members", [
            {"team_id": "t1", "user_id": "owner-1", "role": "owner"},
            {"team_id": "t1", "user_id": "admin-1", "role": "admin"},
            {"team_id": "t1", "user_id": "member-1", "role": "member"},
        ])

    def test_owner_and_admin_can_manage(self):
        assert can_manage_team(self.db, "t1", "owner-1") is True
        assert can_manage_team(self.db, "t1", "admin-1") is True

    def test_plain_member_cannot_manage(self):
        assert can_manage_team(self.db, "t1", "member-1") is False

    def test_non_member_cannot_manage(self):
        assert can_manage_team(self.db, "t1", "stranger") is False

    def test_all_roles_count_as_team_member(self):
        assert is_team_member(self.db, "t1", "member-1") is True


class TestUserCanAccessReport:
    def setup_method(self):
        self.db = FakeSupabase()
        self.db.seed("team_members", [
            {"team_id": "team-a", "user_id": "teammate-1", "role": "member"},
        ])

    def test_owner_always_has_access(self):
        report = {"user_id": "owner-1", "team_id": None}
        assert user_can_access_report(self.db, report, "owner-1") is True

    def test_stranger_with_no_team_share_denied(self):
        report = {"user_id": "owner-1", "team_id": None}
        assert user_can_access_report(self.db, report, "stranger") is False

    def test_team_member_can_access_shared_report(self):
        report = {"user_id": "owner-1", "team_id": "team-a"}
        assert user_can_access_report(self.db, report, "teammate-1") is True

    def test_non_team_member_denied_even_if_report_is_shared(self):
        report = {"user_id": "owner-1", "team_id": "team-a"}
        assert user_can_access_report(self.db, report, "outsider") is False

    def test_owner_has_access_regardless_of_team_sharing(self):
        report = {"user_id": "owner-1", "team_id": "some-other-team"}
        assert user_can_access_report(self.db, report, "owner-1") is True


class TestAcceptPendingInvites:
    """These run against a private SQLite file. accept_pending_invites_for_email
    consults the durable store as well as the client it is handed, so without
    isolation the count here depends on which other tests happened to invite
    the same address earlier in the session."""

    @pytest.fixture(autouse=True)
    def isolated(self, fresh_local_db):
        yield

    def setup_method(self):
        self.db = FakeSupabase()
        self.db.seed("team_invites", [
            {"id": "inv-1", "team_id": "t1", "email": "new@example.com", "status": "pending"},
            {"id": "inv-2", "team_id": "t2", "email": "new@example.com", "status": "pending"},
            {"id": "inv-3", "team_id": "t1", "email": "someone-else@example.com", "status": "pending"},
        ])

    def test_accepts_all_pending_invites_for_matching_email(self):
        accepted = accept_pending_invites_for_email(self.db, "user-123", "new@example.com")
        assert accepted == 2

    def test_creates_team_membership_rows(self):
        accept_pending_invites_for_email(self.db, "user-123", "new@example.com")
        members = self.db._store.get("team_members", [])
        team_ids = {m["team_id"] for m in members if m["user_id"] == "user-123"}
        assert team_ids == {"t1", "t2"}

    def test_marks_invites_accepted_not_reusable(self):
        accept_pending_invites_for_email(self.db, "user-123", "new@example.com")
        second_call = accept_pending_invites_for_email(self.db, "user-123", "new@example.com")
        assert second_call == 0  # already accepted, no longer pending

    def test_no_matching_invites_returns_zero(self):
        accepted = accept_pending_invites_for_email(self.db, "user-999", "nobody@example.com")
        assert accepted == 0

    def test_no_db_returns_zero_gracefully(self):
        assert accept_pending_invites_for_email(None, "user-123", "new@example.com") == 0

    def test_does_not_affect_other_peoples_invites(self):
        accept_pending_invites_for_email(self.db, "user-123", "new@example.com")
        invites = self.db._store.get("team_invites", [])
        other_invite = next(i for i in invites if i["id"] == "inv-3")
        assert other_invite["status"] == "pending"
