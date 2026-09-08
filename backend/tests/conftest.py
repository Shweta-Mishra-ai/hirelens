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
