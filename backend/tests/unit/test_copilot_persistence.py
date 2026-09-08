"""
HireLens — Interview Co-Pilot save-durability regression tests
Run: cd backend && python -m pytest tests/unit/test_copilot_persistence.py -v

Context: save_copilot_data() had a branch that reported success without
persisting anything. When Supabase IS configured and the report row exists
and the recruiter may access it, but the UPDATE comes back empty (the row
changed underneath, a write policy rejected it, PostgREST returned no
representation), `saved` stayed False while `found` was True — and the only
guard was `if not saved and not found`, so that combination fell straight
through to `return {"status": "ok"}`.

That is the worst possible failure shape for this particular feature: a
recruiter types up a full scorecard during a live interview, sees "Saved",
closes the tab, and the notes are gone. Failing loudly (503) keeps the notes
on screen and lets them retry.

These tests drive the endpoint function directly with a stub DB client, since
the bug is entirely in the persistence branch logic.
"""
import asyncio

import pytest

from app.api.v1.endpoints.copilot import save_copilot_data, CoPilotSaveRequest
from app.api.v1.endpoints.analysis import _jobs
from app.core.exceptions import NotFoundError, PersistenceError

USER = {"id": "user-copilot-1", "email": "recruiter@example.com"}
REPORT_ID = "report-copilot-1"


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Minimal stand-in for the supabase-py fluent query builder."""

    def __init__(self, table):
        self._table = table

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self._table.updates.append(payload)
        return _UpdateQuery(self._table)

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _Result(self._table.row)


class _UpdateQuery:
    def __init__(self, table):
        self._table = table

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        return _Result(self._table.update_returns)


class _StubDb:
    def __init__(self, row, update_returns):
        self.row = row
        self.update_returns = update_returns
        self.updates = []

    def table(self, _name):
        return _Query(self)


def _body():
    return CoPilotSaveRequest(
        scorecard=[{"category": "technical", "score": 4, "notes": "solid"}],
        custom_questions=[],
        interview_notes="Candidate walked through the migration in detail.",
        recommendation_override="advance",
    )


def _owned_row():
    return {"id": REPORT_ID, "user_id": USER["id"], "team_id": None, "report_data": {}}


def test_save_reports_failure_when_update_persists_nothing():
    """The regression: row found + accessible, but the UPDATE wrote nothing."""
    db = _StubDb(row=_owned_row(), update_returns=[])

    with pytest.raises(PersistenceError) as exc:
        asyncio.run(save_copilot_data(REPORT_ID, _body(), current_user=USER, db=db))

    # The recruiter must be told to retry, not told it saved.
    assert exc.value.http_status == 503
    assert "retry" in exc.value.message.lower()


def test_save_succeeds_when_update_returns_the_row():
    db = _StubDb(row=_owned_row(), update_returns=[{"id": REPORT_ID}])

    res = asyncio.run(save_copilot_data(REPORT_ID, _body(), current_user=USER, db=db))

    assert res["status"] == "ok"
    assert res["report_id"] == REPORT_ID
    assert res["copilot"]["interview_notes"].startswith("Candidate walked through")
    # And the payload actually reached the update call.
    assert db.updates and "copilot_data" in db.updates[0]["report_data"]


def test_save_on_unknown_report_is_404_not_a_false_ok():
    db = _StubDb(row=None, update_returns=[])

    with pytest.raises(NotFoundError):
        asyncio.run(save_copilot_data("no-such-report", _body(), current_user=USER, db=db))


def test_save_falls_back_to_the_in_memory_job_when_db_write_fails():
    """A DB miss must not lose the notes if the report is still in memory."""
    key = f"report_{REPORT_ID}"
    _jobs[key] = {"_owner_user_id": USER["id"], "candidate": {"name": "Ada"}}
    try:
        db = _StubDb(row=None, update_returns=[])
        res = asyncio.run(save_copilot_data(REPORT_ID, _body(), current_user=USER, db=db))
        assert res["status"] == "ok"
        assert _jobs[key]["copilot_data"]["recommendation_override"] == "advance"
    finally:
        _jobs.pop(key, None)


def test_save_on_someone_elses_in_memory_report_is_404():
    key = f"report_{REPORT_ID}"
    _jobs[key] = {"_owner_user_id": "a-different-user", "candidate": {"name": "Ada"}}
    try:
        with pytest.raises(NotFoundError):
            asyncio.run(save_copilot_data(REPORT_ID, _body(), current_user=USER, db=None))
    finally:
        _jobs.pop(key, None)
