"""
HireLens — the report listing and the CSV export must answer alike
Run: cd backend && python -m pytest tests/unit/test_report_query_consistency.py -v

These two endpoints answer the same question — "which of my reports match
these filters" — and each had its own copy of the logic. They had already
drifted, with a consequence the recruiter sees and the logs do not:

When the skills JSON-path search clause is rejected by PostgREST,
list_reports caught the failure and retried with a name/file-only filter, so
the dashboard showed rows. The export's try/except sat around `.or_()`,
which only builds a filter string and cannot raise — so the real failure at
`.execute()` fell through to `items = []` and produced a CSV containing
nothing but the header.

Same user, same search, same instant: candidates on screen, an empty file on
disk. Nothing errored. The only conclusion available to the recruiter is
that their pipeline is empty or the export is broken.

The fix is one implementation used by both. These tests pin that: they drive
the shared helper directly with a database stub that fails the way PostgREST
does, and they assert the two endpoints call the same code.
"""

import inspect

import pytest

from app.api.v1.endpoints import reports


class _Query:
    """Stub PostgREST query builder.

    `fail_on_skills` reproduces the real failure: the clause is accepted when
    it is built and rejected when it is executed.
    """

    def __init__(self, table, rows, fail_on_skills):
        self._table = table
        self._rows = rows
        self._fail_on_skills = fail_on_skills
        self._has_skills_clause = False
        self.count = len(rows)

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def or_(self, clause):
        self._table.or_clauses.append(clause)
        if "report_data->skills" in clause:
            self._has_skills_clause = True
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self._has_skills_clause and self._fail_on_skills:
            raise RuntimeError('unsupported operator: "report_data->skills->>all_claimed"')
        self._table.executed += 1
        return self


class _Db:
    def __init__(self, rows, fail_on_skills=False):
        self.rows = rows
        self.fail_on_skills = fail_on_skills
        self.or_clauses: list[str] = []
        self.executed = 0

    def table(self, name):
        q = _Query(self, self.rows, self.fail_on_skills)
        q.data = self.rows
        return q


ROWS = [
    {
        "id": "r1",
        "file_name": "ada.pdf",
        "candidate_name": "Ada Lovelace",
        "overall_score": 88,
        "recommendation": "recommended",
        "created_at": "2026-01-01",
        "recruiter_decision": None,
    }
]


def _fetch(db, search="ada"):
    return reports._fetch_reports(
        db, "user-1", None, search, "created_at", True, offset=0, limit=100
    )


class TestSkillPathFallback:
    def test_the_skills_clause_is_used_when_it_works(self):
        db = _Db(ROWS)
        assert _fetch(db) == ROWS
        assert any("report_data->skills" in c for c in db.or_clauses)

    def test_a_rejected_skills_clause_falls_back_instead_of_returning_nothing(self):
        """The bug: an empty result where rows exist."""
        db = _Db(ROWS, fail_on_skills=True)

        result = _fetch(db)

        assert result == ROWS, "a failed skills clause must degrade to a name/file search"
        # The retry must actually drop the offending clause, not just repeat it.
        assert db.or_clauses[-1] == "candidate_name.ilike.%ada%,file_name.ilike.%ada%"

    def test_a_failure_without_a_search_is_not_swallowed(self):
        """Only the JSON-path clause is expected to be unsupported. Any other
        failure is a real error and must surface, not silently return []."""

        class AlwaysFails(_Db):
            def table(self, name):
                q = super().table(name)
                q.execute = lambda: (_ for _ in ()).throw(RuntimeError("connection reset"))
                return q

        with pytest.raises(RuntimeError):
            _fetch(AlwaysFails(ROWS), search=None)


class TestBothEndpointsShareOneImplementation:
    """A shared helper that only one caller uses is not shared."""

    def test_list_reports_uses_the_shared_fetch(self):
        src = inspect.getsource(reports.list_reports)
        assert "_fetch_reports" in src
        assert "_filter_mem_reports" in src

    def test_the_export_uses_the_same_shared_fetch(self):
        src = inspect.getsource(reports.export_all_reports_csv)
        assert "_fetch_reports" in src
        assert "_filter_mem_reports" in src

    def test_neither_builds_its_own_query(self):
        """If a caller starts assembling `db.table("reports").select(...)`
        again, the two can drift apart again."""
        for fn in (reports.list_reports, reports.export_all_reports_csv):
            src = inspect.getsource(fn)
            assert 'db.table("reports").select(REPORT_LIST_COLUMNS)' not in src
            assert "ilike" not in src, f"{fn.__name__} is hand-building a search filter again"

    def test_the_in_memory_path_is_shared_too(self):
        """The fallback store had its own duplicated copy of the same
        filtering, sorting and _skills_text cleanup."""
        items = reports._filter_mem_reports("nobody", None, None, "created_at", True)
        assert items == []
