"""
Shared pytest fixtures.

The most important thing here is test isolation for the local SQLite store.
Before this file existed, `app.core.local_db` wrote to `backend/data/local.db`
— a real file in the working tree — during every test run. Two consequences:

  * Tests leaked state into each other and into subsequent runs. A test that
    signed up `e2e_recruiter@example.com` would pass on a clean checkout and
    fail on the next run, because the second signup correctly reported the
    account already existed. The suite was green only by virtue of CI always
    starting from a fresh clone.
  * Running the dev server locally and then running the tests would fail,
    because the server had already populated the same file.

`HIRELENS_LOCAL_DB_PATH` is set before `app` is imported anywhere, so every
connection opened during the session lands in a throwaway directory.
"""

import os
import tempfile
from pathlib import Path

import pytest

# Must happen at import time, before any test module imports app.* — local_db
# resolves this on every connection, but app.main's startup runs on import.
_TMP_DIR = tempfile.mkdtemp(prefix="hirelens-tests-")
os.environ["HIRELENS_LOCAL_DB_PATH"] = str(Path(_TMP_DIR) / "test.db")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only-not-production")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")


@pytest.fixture(autouse=True)
def isolate_stores():
    """
    Reset the process-local stores between tests so ordering cannot change
    outcomes. These are module-level dicts that live for the whole
    interpreter and are shared by every test that touches them.

    The rate limiter matters most here. `_mem_rate_limit` is the fallback
    used whenever Redis is unconfigured — which is always, under test. Its
    windows are 15 minutes (login) and 1 hour (signup), far longer than a
    test session, so without this reset the Nth signup across the *entire
    suite* starts returning 429. That coupling is invisible until someone
    adds a test that signs up, at which point unrelated tests in other files
    begin failing with `rate_limit_exceeded` in place of whatever they
    actually asserted.

    Cleared before the test as well as after, so a test is unaffected by
    whatever ran ahead of it even on a partial run (`pytest -k`).
    """
    from app.api.v1.endpoints import auth as auth_ep
    from app.api.v1.endpoints.analysis import _jobs
    from app.core.rate_limit import _mem_rate_limit

    def _reset():
        _mem_rate_limit.clear()
        auth_ep._mem_users.clear()
        try:
            _jobs.clear()
        except Exception:
            # PersistentJobStore may be Redis-backed in some configurations;
            # failing to clear it must not fail the test that just passed.
            pass

    _reset()
    yield
    _reset()


@pytest.fixture
def fresh_local_db():
    """Give a single test a private SQLite file."""
    with tempfile.TemporaryDirectory() as d:
        prev = os.environ.get("HIRELENS_LOCAL_DB_PATH")
        os.environ["HIRELENS_LOCAL_DB_PATH"] = str(Path(d) / "isolated.db")
        from app.core import local_db

        local_db.init_local_db()
        try:
            yield local_db
        finally:
            if prev is None:
                os.environ.pop("HIRELENS_LOCAL_DB_PATH", None)
            else:
                os.environ["HIRELENS_LOCAL_DB_PATH"] = prev
