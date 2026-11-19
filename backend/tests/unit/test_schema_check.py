"""
The schema check: does it tell an operator exactly which migration is
missing, and only when one really is?

Errors are built with postgrest's own APIError and the codes PostgREST
returns, so the classifier is tested against the shapes production sees
(tests/postgrest checks the same against a real PostgREST server).
"""

import logging

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.core import schema_check
from app.core.dependencies import get_db, get_redis


def _missing_table(table):
    return APIError({
        "code": "PGRST205",
        "message": f"Could not find the table 'public.{table}' in the schema cache",
        "details": None,
        "hint": None,
    })


def _missing_column(table, column):
    return APIError({
        "code": "42703",
        "message": f"column {table}.{column} does not exist",
        "details": None,
        "hint": None,
    })


class _Probe:
    def __init__(self, db, table):
        self.db, self.table, self.columns, self.n = db, table, "", None

    def select(self, columns):
        self.columns = columns
        return self

    def limit(self, n):
        self.n = n
        return self

    def execute(self):
        self.db.calls.append((self.table, self.columns, self.n))
        if self.table in self.db.missing_tables:
            raise _missing_table(self.table)
        for column in self.columns.split(","):
            if (self.table, column) in self.db.missing_columns:
                raise _missing_column(self.table, column)
        if self.db.broken:
            raise ConnectionError("Name or service not known")
        return type("R", (), {"data": []})()


class SchemaDB:
    def __init__(self, missing_tables=(), missing_columns=(), broken=False):
        self.missing_tables = set(missing_tables)
        self.missing_columns = set(missing_columns)
        self.broken = broken
        self.calls = []

    def table(self, name):
        return _Probe(self, name)


@pytest.fixture(autouse=True)
def _fresh_cache():
    schema_check.clear_cache()
    yield
    schema_check.clear_cache()


class TestCheck:
    def test_a_fully_migrated_database_is_ok(self):
        report = schema_check.check(SchemaDB())
        assert report.status == "ok"
        assert report.missing == {} and report.errors == {}

    def test_names_the_file_that_creates_a_missing_table(self):
        report = schema_check.check(SchemaDB(missing_tables={"usage_events", "subscriptions"}))
        assert report.status == "missing"
        assert report.missing == {"007_billing_and_usage.sql": ["subscriptions", "usage_events"]}
        assert "plan limits are NOT enforced" in report.describe()

    def test_names_the_file_that_adds_a_missing_column(self):
        db = SchemaDB(missing_columns={("reports", "candidate_notified_at")})
        report = schema_check.check(db)
        assert report.missing == {"003_candidate_notifications.sql": ["reports.candidate_notified_at"]}

    def test_a_missing_table_is_reported_once_under_the_file_that_creates_it(self):
        # reports is used by 001, 002 and 003; without the table, only 001 is
        # the fix, and the later files' probes are skipped rather than
        # reported as three separate problems.
        report = schema_check.check(SchemaDB(missing_tables={"reports"}))
        assert report.missing == {"001_core_schema.sql": ["reports"]}

    def test_an_unreachable_database_is_unknown_not_missing(self):
        # Telling an operator to run a migration that is already there sends
        # them the wrong way.
        report = schema_check.check(SchemaDB(broken=True))
        assert report.status == "unknown"
        assert report.missing == {}
        assert report.public_status == "unknown"

    def test_no_database_is_unknown(self):
        assert schema_check.check(None).status == "unknown"

    def test_probes_read_no_rows(self):
        db = SchemaDB()
        schema_check.check(db)
        assert db.calls, "nothing was probed"
        assert {n for _, _, n in db.calls} == {0}

    def test_every_requirement_names_a_real_migration_file(self):
        from pathlib import Path
        sql = Path(__file__).resolve().parents[2] / "sql"
        for migration, _, _ in schema_check.REQUIREMENTS:
            assert (sql / migration).is_file(), migration
            assert migration in schema_check.CONSEQUENCES


class TestCache:
    def test_reuses_a_recent_result(self):
        db = SchemaDB()
        schema_check.cached(db)
        first = len(db.calls)
        schema_check.cached(db)
        assert len(db.calls) == first

    def test_max_age_zero_forces_a_fresh_check(self):
        db = SchemaDB()
        schema_check.cached(db)
        first = len(db.calls)
        schema_check.cached(db, 0)
        assert len(db.calls) == 2 * first


class TestLogging:
    def test_missing_migrations_are_critical_and_name_the_files(self, caplog):
        report = schema_check.check(SchemaDB(missing_tables={"session_revocations"}))
        with caplog.at_level(logging.CRITICAL, logger="hirelens"):
            schema_check.log_report(report)
        assert "008_sessions_and_invite_fk.sql" in caplog.text
        assert "Sign out of all devices" in caplog.text


class TestHealthEndpoint:
    @pytest.fixture
    def client(self):
        from app.main import app
        db = SchemaDB(missing_tables={"usage_events", "subscriptions"})
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_redis] = lambda: None
        yield TestClient(app)
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_redis, None)

    def test_public_health_says_migrations_are_missing_without_naming_tables(self, client):
        body = client.get("/api/v1/health").json()
        assert body["services"]["schema"] == "missing_migrations"
        assert body["status"] == "degraded"
        assert "usage_events" not in str(body)
        assert "errors" not in body

    def test_diagnostics_snapshot_names_the_file_to_run(self):
        from app.api.v1.endpoints.health import _snapshot
        snap = _snapshot(SchemaDB(missing_tables={"usage_events"}), None)
        assert "007_billing_and_usage.sql" in snap["errors"]["schema"]

    def test_a_healthy_schema_reports_ok(self):
        from app.api.v1.endpoints.health import _snapshot
        snap = _snapshot(SchemaDB(), None)
        assert snap["services"]["schema"] == "ok"
        assert "schema" not in snap["errors"]
