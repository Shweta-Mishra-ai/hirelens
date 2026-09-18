"""
No undefined names anywhere in app/.

This exists because of a real miss. A batch edit replaced calls in
copilot.py with `as_dict(...)` but never added the import. Python only
raises NameError when the line runs, that line lives inside a
`try/except Exception` that logs and moves on, and the fallback path made
the endpoint still answer 200 — so saving interview notes silently stopped
working on the Supabase path and every existing test stayed green.

A missing name is not a style issue; it is a runtime error waiting for a
particular request. pyflakes finds them in milliseconds.
"""

import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"

# Only the errors that mean "this will raise when it runs". Unused imports
# and similar tidiness notes are deliberately not failures here.
FATAL = ("undefined name", "redefinition of unused", "f-string is missing placeholders")


@pytest.fixture(scope="module")
def pyflakes_output() -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyflakes", str(APP)],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("pyflakes is not installed")
    if result.returncode not in (0, 1):
        pytest.skip(f"pyflakes could not run: {result.stderr.strip()[:200]}")
    return result.stdout


def test_no_name_is_used_before_it_is_imported_or_defined(pyflakes_output):
    fatal = [
        line for line in pyflakes_output.splitlines()
        if any(marker in line for marker in FATAL)
    ]
    assert not fatal, "pyflakes found names that will raise at runtime:\n" + "\n".join(fatal)


def test_every_endpoint_module_imports_cleanly():
    """A module that cannot be imported takes the whole API down at startup."""
    import importlib

    for path in sorted((APP / "api" / "v1" / "endpoints").glob("*.py")):
        if path.stem == "__init__":
            continue
        importlib.import_module(f"app.api.v1.endpoints.{path.stem}")
