"""
The fake Supabase client has to describe the real tables.

tests/fake_supabase.py rejects a write naming a column the table does not
have, which is how PostgREST behaves — and that guard is only worth
anything while its column lists match backend/sql/. They drifted once
already: create_team inserted an "id" into team_members, a table that has
no id column, and because the fake accepted the extra key no test noticed
that PostgREST was refusing the insert in production.

So the lists are checked against the SQL files rather than trusted.
"""

import re
from pathlib import Path

import pytest

from tests.fake_supabase import SCHEMA

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def columns_from_sql() -> dict[str, set[str]]:
    """Parse CREATE TABLE and ALTER TABLE ... ADD COLUMN out of backend/sql/."""
    tables: dict[str, set[str]] = {}
    sql = "\n".join(p.read_text() for p in sorted(SQL_DIR.glob("*.sql")))

    for match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS public\.([a-z_]+)\s*\((.*?)\n\);", sql, re.S
    ):
        table, body = match.group(1), match.group(2)
        columns = set()
        for line in body.split("\n"):
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            first = line.split()[0]
            if first.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
                continue
            columns.add(first.strip(","))
        tables[table] = columns

    for match in re.finditer(
        r"ALTER TABLE public\.([a-z_]+)\s*(.*?);", sql, re.S
    ):
        table, body = match.group(1), match.group(2)
        for column in re.findall(r"ADD COLUMN IF NOT EXISTS\s+([a-z_]+)", body):
            tables.setdefault(table, set()).add(column)

    return tables


@pytest.fixture(scope="module")
def real() -> dict[str, set[str]]:
    parsed = columns_from_sql()
    assert parsed, f"no CREATE TABLE statements found under {SQL_DIR}"
    return parsed


def test_every_table_the_code_writes_to_is_declared(real):
    assert set(SCHEMA) == set(real), (
        f"only in the fake: {sorted(set(SCHEMA) - set(real))}; "
        f"only in sql/: {sorted(set(real) - set(SCHEMA))}"
    )


@pytest.mark.parametrize("table", sorted(SCHEMA))
def test_the_fake_lists_exactly_the_real_columns(table, real):
    assert SCHEMA[table] == real[table], (
        f"{table}: only in the fake {sorted(SCHEMA[table] - real[table])}, "
        f"only in sql/ {sorted(real[table] - SCHEMA[table])}"
    )


def test_the_sql_files_are_ordered_so_they_can_be_run_in_sequence():
    """002 adds a column to reports and foreign-keys four tables to it, so
    reports has to be created by a file that sorts before it."""
    names = sorted(p.name for p in SQL_DIR.glob("*.sql"))
    assert names[0].startswith("001"), names
    creating = next(p for p in sorted(SQL_DIR.glob("*.sql"))
                    if "CREATE TABLE IF NOT EXISTS public.reports" in p.read_text())
    referencing = next(p for p in sorted(SQL_DIR.glob("*.sql"))
                       if "REFERENCES public.reports" in p.read_text())
    assert creating.name < referencing.name
