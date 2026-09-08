"""
Shared pytest configuration.

The important thing this file does is make the suite hermetic.

Without it, `app/core/local_db.py` wrote to the developer's real
`backend/data/local.db` — the same file the dev server uses — so every test
run left accounts behind. The consequence was a suite that only passed on a
clean checkout: run `pytest` twice on the same machine and the auth and e2e
tests failed on "email already registered", because a user the previous run
created was still there. CI never saw it (a fresh runner every time), which
is the worst version of this problem: the failure only ever shows up locally,
so it gets written off as "a stale local file" and deleted, and the next
person hits it again.

Pointing HIRELENS_LOCAL_DB_PATH at a per-run temp file fixes it at the root:
every run starts from an empty database, the dev's own local.db is never
touched by tests, and a failure is now always a real failure.

This must run before anything imports app.core.local_db, which is why it is
at module scope in conftest.py rather than inside a fixture — pytest imports
conftest before collecting any test module.
"""

import os
import tempfile
from pathlib import Path

_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="hirelens-test-db-"))
os.environ["HIRELENS_LOCAL_DB_PATH"] = str(_TEST_DB_DIR / "local.db")

# Deterministic, non-production settings for the app under test. Set here
# rather than relying on a developer's ambient .env so that a stray
# APP_ENV=production or a real SUPABASE_URL in the shell can't change what
# the suite actually exercises.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only-not-a-real-key")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")


import pytest


@pytest.fixture(autouse=True)
def reset_global_caches():
    """Undo module-level state a test may have poisoned.

    Two globals in this app are created once and reused: the Supabase/Redis
    clients in app.core.dependencies, and the in-process token-revocation
    denylist. Both survive a monkeypatch being undone, so a test that sets
    REDIS_URL leaves a cached client pointing at a Redis that isn't there,
    and every later test in the run inherits it. That is exactly how a
    revocation bug surfaced as an unrelated session test failing several
    files away — the sort of failure that gets chased in the wrong file.

    Resetting after each test keeps a failure local to the test that caused
    it.
    """
    yield
    from app.core import dependencies, rate_limit, token_revocation

    dependencies._redis_client = None
    token_revocation._reset_for_tests()

    # The in-memory rate-limit buckets are global and keyed by client IP —
    # which is the literal string "testclient" for every test. Left alone,
    # signups across the whole run share one 8-per-hour budget, so after
    # enough of them EVERY later test that needs an account starts failing
    # with a 401 that says "Invalid email or password" and points nowhere
    # near the real cause. That made outcomes depend on execution order:
    # adding a test in one file could break an unrelated file. One suite
    # happened to clear this in its own fixture, which is what was quietly
    # holding the whole thing together.
    rate_limit._mem_rate_limit.clear()
