"""
A small in-memory stand-in for the Supabase (PostgREST) client.

Almost every endpoint in this codebase has two branches: a Supabase one and
a local-SQLite fallback. The test suite only ever ran the fallback, because
SUPABASE_URL is unset under test — which meant the branch that runs in
production was the untested one. This fake implements enough of the query
builder to exercise it: filtering, ordering, ranging, exact counts, update
and delete, plus a way to make any particular call blow up so the error
handling around it can be checked too.

It is deliberately strict about one thing: `.execute()` is synchronous,
matching supabase-py v2. If a caller ever `await`s it, the test fails the
same way production would.
"""

from __future__ import annotations

import re
from typing import Any, Callable


class Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


def _matches_ilike(value: Any, pattern: str) -> bool:
    """SQL ILIKE: % is any run of characters, _ is any single one."""
    if value is None:
        return False
    regex = "^" + "".join(
        ".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern
    ) + "$"
    return re.match(regex, str(value), re.IGNORECASE) is not None


class _Query:
    def __init__(self, client: "FakeSupabase", table: str):
        self.client = client
        self.table_name = table
        self.filters: list[Callable[[dict], bool]] = []
        self.or_filters: list[Callable[[dict], bool]] = []
        self.order_by: tuple[str, bool] | None = None
        self.range_: tuple[int, int] | None = None
        self.limit_: int | None = None
        self.single = False
        self.count_mode: str | None = None
        self.op = "select"
        self.payload: dict | None = None
        self.json_path_rejected: str | None = None
        self.on_conflict: list[str] = []

    # ── builder ────────────────────────────────────────────────────────────
    def select(self, _columns="*", count=None):
        self.op = "select"
        self.count_mode = count
        return self

    def update(self, payload: dict):
        self.op = "update"
        self.payload = payload
        return self

    def insert(self, payload: dict):
        self.op = "insert"
        self.payload = payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column: str, value):
        self.filters.append(lambda row, c=column, v=value: row.get(c) == v)
        return self

    def in_(self, column: str, values):
        wanted = list(values)
        self.filters.append(lambda row, c=column, v=wanted: row.get(c) in v)
        return self

    def neq(self, column: str, value):
        self.filters.append(lambda row, c=column, v=value: row.get(c) != v)
        return self

    def or_(self, expression: str):
        """Supports the `col.ilike.%x%` form this codebase builds."""
        clauses = []
        for part in expression.split(","):
            part = part.strip()
            if not part:
                continue
            column, _, pattern = part.partition(".ilike.")
            if not _:
                continue
            if "->" in column:
                # A JSON-path filter. PostgREST supports these; whether a
                # given deployment does is exactly what the fallback in
                # list_reports exists for, so let the fake refuse them when
                # asked to. The refusal is deferred to execute(), because
                # .or_() only builds the filter — it makes no network call
                # and so cannot raise in the real client either.
                if self.client.reject_json_path:
                    self.json_path_rejected = column
                column = column.split("->")[0]
            clauses.append((column, pattern))

        def any_clause(row):
            return any(_matches_ilike(row.get(c), p) for c, p in clauses)

        self.or_filters.append(any_clause)
        return self

    def order(self, column: str, desc: bool = False):
        self.order_by = (column, desc)
        return self

    def range(self, start: int, end: int):
        self.range_ = (start, end)
        return self

    def limit(self, n: int):
        self.limit_ = n
        return self

    def maybe_single(self):
        self.single = True
        return self

    def upsert(self, payload: dict, on_conflict=None):
        self.op = "upsert"
        self.payload = payload
        self.on_conflict = [c.strip() for c in (on_conflict or "").split(",") if c.strip()]
        return self

    # ── execution ──────────────────────────────────────────────────────────
    def _rows(self):
        rows = self.client.tables.get(self.table_name, [])
        out = [r for r in rows if all(f(r) for f in self.filters)]
        for f in self.or_filters:
            out = [r for r in out if f(r)]
        return out

    def execute(self):
        self.client.calls.append((self.table_name, self.op))
        self.client.maybe_fail(self.table_name, self.op)
        if self.json_path_rejected:
            raise RuntimeError(
                f"operator does not exist: jsonb ~~* unknown ({self.json_path_rejected})"
            )

        if self.op in ("insert", "upsert"):
            self.client.check_columns(self.table_name, self.payload or {})
            payload = dict(self.payload or {})
            rows = self.client.tables.setdefault(self.table_name, [])
            if self.op == "upsert" and self.on_conflict:
                for row in rows:
                    if all(row.get(c) == payload.get(c) for c in self.on_conflict):
                        row.update(payload)
                        return Result([dict(row)])
            payload.setdefault("id", f"{self.table_name}-{len(rows) + 1}")
            payload.setdefault("created_at", f"2026-01-01T00:00:{len(rows):02d}+00:00")
            rows.append(payload)
            return Result([dict(payload)])

        matched = self._rows()

        if self.op == "update":
            self.client.check_columns(self.table_name, self.payload or {})
            for row in matched:
                row.update(self.payload or {})
            return Result([dict(r) for r in matched])

        if self.op == "delete":
            table = self.client.tables.get(self.table_name, [])
            self.client.tables[self.table_name] = [r for r in table if r not in matched]
            return Result([dict(r) for r in matched])

        total = len(matched)
        if self.order_by:
            column, desc = self.order_by
            matched = sorted(matched, key=lambda r: (r.get(column) is None, r.get(column) or ""), reverse=desc)
        if self.range_:
            start, end = self.range_
            matched = matched[start: end + 1]
        if self.limit_ is not None:
            matched = matched[: self.limit_]

        if self.single:
            return Result(dict(matched[0]) if matched else None)

        return Result(
            [dict(r) for r in matched],
            count=total if self.count_mode == "exact" else None,
        )


# The real column list for each table, from backend/sql/*.sql. A write naming
# anything else is what PostgREST rejects, so the fake rejects it too.
#
# This is not pedantry: create_team used to insert an "id" into team_members,
# a table keyed on (team_id, user_id) with no id column. PostgREST refused the
# whole insert, the endpoint swallowed the error, and the team ended up in
# Supabase with its owner holding no membership row. The fake happily accepted
# the extra key, so no test noticed.
SCHEMA: dict[str, set[str]] = {
    "reports": {
        "id", "user_id", "job_id", "file_name", "candidate_name", "overall_score",
        "recommendation", "report_data", "recruiter_decision", "decision_notes",
        "created_at", "updated_at", "team_id", "candidate_notified_at",
        "candidate_notified_decision",
    },
    "profiles": {"id", "email", "full_name", "company", "created_at", "updated_at"},
    "teams": {"id", "name", "owner_id", "created_at"},
    "team_members": {"team_id", "user_id", "role", "joined_at"},
    "team_invites": {"id", "team_id", "email", "invited_by", "status", "created_at"},
    "report_comments": {"id", "report_id", "user_id", "comment", "created_at"},
    "report_votes": {"report_id", "user_id", "vote", "created_at"},
}


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]] | None = None, strict: bool = True):
        self.tables = tables or {}
        self.calls: list[tuple[str, str]] = []
        # (table, op) pairs that should raise, and whether to keep raising.
        self.failures: dict[tuple[str, str], int] = {}
        self.reject_json_path = False
        # Reject writes naming a column the real table does not have.
        self.strict = strict

    def check_columns(self, table: str, payload: dict) -> None:
        if not self.strict:
            return
        known = SCHEMA.get(table)
        if known is None:
            return
        unknown = sorted(set(payload or {}) - known)
        if unknown:
            raise RuntimeError(
                f"PGRST204: column {table}.{unknown[0]!r} does not exist"
            )

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def fail(self, table: str, op: str = "select", times: int = 10**6):
        self.failures[(table, op)] = times

    def maybe_fail(self, table: str, op: str):
        key = (table, op)
        remaining = self.failures.get(key, 0)
        if remaining > 0:
            self.failures[key] = remaining - 1
            raise RuntimeError(f"simulated {op} failure on {table}")
