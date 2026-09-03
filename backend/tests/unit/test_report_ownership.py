"""
HireLens — In-Memory Report Ownership Regression Tests
Run: cd backend && python -m pytest tests/unit/test_report_ownership.py -v

These exist specifically to prevent the access-control bug found in the
July 2026 audit from silently coming back. The root cause was: report
blobs written to the in-memory fallback store (`_jobs`) never carried an
owner, so every read/list/delete path on that fallback either treated
"no owner recorded" as "visible to everyone" (list, get) or didn't check
ownership at all (delete). This is fixed by stamping `_owner_user_id` at
write time and checking it on every read/list/delete.

Each test below operates directly on the shared `_jobs` dict the same way
the endpoints do, rather than mocking Supabase — the bug was entirely in
the in-memory path, so that's what needs direct coverage.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.api.v1.endpoints.analysis import _jobs
from app.core.exceptions import ForbiddenError, NotFoundError


def _fake_report(owner_user_id: str | None, candidate_name: str = "Test Candidate", **extra) -> dict:
    base = {
        "candidate": {"name": candidate_name},
        "credibility": {"overall": 70, "recommendation": "manual_review"},
        "recruiter_decision": None,
    }
    if owner_user_id is not None:
        base["_owner_user_id"] = owner_user_id
    base.update(extra)
    return base


class TestGetReportOwnership:
    """C-01: any logged-in user could previously read any in-memory report."""

    def setup_method(self):
        self._keys_before = set(_jobs.keys())

    def teardown_method(self):
        for k in list(_jobs.keys()):
            if k not in self._keys_before:
                _jobs.pop(k, None)

    def test_owner_can_read_their_own_inmemory_report(self):
        from app.api.v1.endpoints.reports import get_report

        report_id = "test-report-owner-read"
        _jobs[f"report_{report_id}"] = _fake_report(owner_user_id="user-a")

        result = asyncio.run(get_report(report_id, current_user={"id": "user-a"}, db=None))
        assert result["candidate"]["name"] == "Test Candidate"

    def test_other_user_cannot_read_inmemory_report(self):
        from app.api.v1.endpoints.reports import get_report

        report_id = "test-report-other-read"
        _jobs[f"report_{report_id}"] = _fake_report(owner_user_id="user-a")

        try:
            asyncio.run(get_report(report_id, current_user={"id": "user-b"}, db=None))
            assert False, "expected ForbiddenError, but the report was returned"
        except ForbiddenError:
            pass

    def test_report_with_no_owner_stamp_is_inaccessible_to_anyone(self):
        """
        Fail closed: a report that somehow has no owner recorded must not
        be treated as "visible to everyone" (the original bug), and also
        must not silently succeed for an arbitrary user.
        """
        from app.api.v1.endpoints.reports import get_report

        report_id = "test-report-no-owner"
        _jobs[f"report_{report_id}"] = _fake_report(owner_user_id=None)

        try:
            asyncio.run(get_report(report_id, current_user={"id": "user-a"}, db=None))
            assert False, "expected ForbiddenError for an unowned report"
        except ForbiddenError:
            pass

    def test_nonexistent_report_raises_not_found_not_forbidden(self):
        from app.api.v1.endpoints.reports import get_report

        try:
            asyncio.run(get_report("does-not-exist-at-all", current_user={"id": "user-a"}, db=None))
            assert False, "expected NotFoundError"
        except NotFoundError:
            pass


class TestListReportsOwnership:
    """C-02: the in-memory report list leaked every user's reports to every user."""

    def setup_method(self):
        self._keys_before = set(_jobs.keys())

    def teardown_method(self):
        for k in list(_jobs.keys()):
            if k not in self._keys_before:
                _jobs.pop(k, None)

    def test_mem_reports_for_user_excludes_other_users_reports(self):
        from app.api.v1.endpoints.reports import _mem_reports_for_user

        _jobs["report_test-list-mine"] = _fake_report(
            owner_user_id="user-a", candidate_name="Mine"
        )
        _jobs["report_test-list-theirs"] = _fake_report(
            owner_user_id="user-b", candidate_name="Theirs"
        )

        results = _mem_reports_for_user("user-a")
        names = [r.get("candidate_name") for r in results]

        assert "Mine" in names
        assert "Theirs" not in names

    def test_mem_reports_for_user_excludes_unowned_reports(self):
        """
        This is the exact bug: v.get("user_id") (a key that never existed)
        defaulted to None, and None was in the allowed tuple — so every
        report with no owner was returned to every caller. Now, no owner
        stamp means the report is excluded, not included.
        """
        from app.api.v1.endpoints.reports import _mem_reports_for_user

        _jobs["report_test-list-unowned"] = _fake_report(
            owner_user_id=None, candidate_name="Nobodys"
        )

        results = _mem_reports_for_user("user-a")
        names = [r.get("candidate_name") for r in results]
        assert "Nobodys" not in names

        results_b = _mem_reports_for_user("user-b")
        names_b = [r.get("candidate_name") for r in results_b]
        assert "Nobodys" not in names_b


class TestDeleteReportOwnership:
    """
    delete_report previously popped any report_id from the in-memory store
    with no ownership check whatsoever.
    """

    def setup_method(self):
        self._keys_before = set(_jobs.keys())

    def teardown_method(self):
        for k in list(_jobs.keys()):
            if k not in self._keys_before:
                _jobs.pop(k, None)

    def test_owner_can_delete_their_own_inmemory_report(self):
        from app.api.v1.endpoints.reports import delete_report

        report_id = "test-report-owner-delete"
        _jobs[f"report_{report_id}"] = _fake_report(owner_user_id="user-a")

        asyncio.run(delete_report(report_id, current_user={"id": "user-a"}, db=None))
        assert f"report_{report_id}" not in _jobs

    def test_other_user_cannot_delete_report_and_it_still_exists(self):
        from app.api.v1.endpoints.reports import delete_report

        report_id = "test-report-other-delete"
        _jobs[f"report_{report_id}"] = _fake_report(owner_user_id="user-a")

        try:
            asyncio.run(delete_report(report_id, current_user={"id": "user-b"}, db=None))
            assert False, "expected ForbiddenError"
        except ForbiddenError:
            pass

        # The critical assertion: the report must still be there afterward.
        assert f"report_{report_id}" in _jobs


class TestSubmitDecisionHonesty:
    """
    F-03: submit_decision always returned {"status": "ok"} even when
    nothing was actually saved (DB error, or zero rows matched). It also
    never wrote anything to the in-memory store, so a decision made while
    the DB was unavailable was silently discarded every time.
    """

    def setup_method(self):
        self._keys_before = set(_jobs.keys())

    def teardown_method(self):
        for k in list(_jobs.keys()):
            if k not in self._keys_before:
                _jobs.pop(k, None)

    def test_decision_persists_to_inmemory_store_when_no_db(self):
        from app.api.v1.endpoints.reports import submit_decision, DecisionRequest

        report_id = "test-decision-mem"
        _jobs[f"report_{report_id}"] = _fake_report(owner_user_id="user-a")

        result = asyncio.run(submit_decision(
            report_id,
            DecisionRequest(decision="advance", notes="looks good"),
            current_user={"id": "user-a"},
            db=None,
        ))

        assert result["status"] == "ok"
        assert _jobs[f"report_{report_id}"]["recruiter_decision"] == "advance"
        assert _jobs[f"report_{report_id}"]["decision_notes"] == "looks good"

    def test_decision_on_nonexistent_report_raises_not_found(self):
        from app.api.v1.endpoints.reports import submit_decision, DecisionRequest

        try:
            asyncio.run(submit_decision(
                "does-not-exist-decision-test",
                DecisionRequest(decision="advance", notes=None),
                current_user={"id": "user-a"},
                db=None,
            ))
            assert False, "expected NotFoundError"
        except NotFoundError:
            pass

    def test_decision_on_someone_elses_report_raises_not_found(self):
        """
        Deliberately NotFoundError, not ForbiddenError, here — same
        information-disclosure reasoning as most "not yours" endpoints:
        don't confirm to an attacker that a report with this ID exists.
        """
        from app.api.v1.endpoints.reports import submit_decision, DecisionRequest

        report_id = "test-decision-not-mine"
        _jobs[f"report_{report_id}"] = _fake_report(owner_user_id="user-a")

        try:
            asyncio.run(submit_decision(
                report_id,
                DecisionRequest(decision="reject", notes=None),
                current_user={"id": "user-b"},
                db=None,
            ))
            assert False, "expected NotFoundError"
        except NotFoundError:
            pass

        # And the original owner's report must be untouched.
        assert _jobs[f"report_{report_id}"]["recruiter_decision"] is None
