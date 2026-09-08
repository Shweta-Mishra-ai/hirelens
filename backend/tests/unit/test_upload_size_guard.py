"""
HireLens — upload size-guard tests
Run: cd backend && python -m pytest tests/unit/test_upload_size_guard.py -v

The 10MB file limit was enforced AFTER `await file.read()` had already pulled
the whole body into memory. A limit you check once you have already paid the
cost it exists to avoid is not a limit: one request with a multi-gigabyte body
buffers that much on a single-worker free-tier container and takes the API
down for everyone.

The same shape existed in bulk upload, where the batch total was only checked
once all 50 files had been read.

The remote-download path in ats.py already streamed with an abort, so this is
bringing the local upload path in line with a pattern the codebase had
already settled on — not inventing one.
"""

import asyncio

import pytest

from app.api.v1.endpoints.analysis import read_upload_capped
from app.core.exceptions import FileTooLarge


class FakeUpload:
    """Minimal UploadFile stand-in that records how much was actually read.

    `bytes_served` is the assertion that matters: it proves the read stopped
    early instead of consuming the whole body and complaining afterwards.
    """

    def __init__(self, total_bytes: int, chunk: int = 64 * 1024):
        self._remaining = total_bytes
        self._chunk = chunk
        self.bytes_served = 0

    async def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        n = self._remaining if size in (-1, None) else min(size, self._remaining)
        self._remaining -= n
        self.bytes_served += n
        return b"x" * n


def test_a_file_within_the_cap_is_read_completely():
    f = FakeUpload(3 * 1024 * 1024)
    data = asyncio.run(read_upload_capped(f, 10 * 1024 * 1024))
    assert len(data) == 3 * 1024 * 1024


def test_an_oversized_file_is_refused():
    f = FakeUpload(20 * 1024 * 1024)
    with pytest.raises(FileTooLarge):
        asyncio.run(read_upload_capped(f, 10 * 1024 * 1024))


def test_the_read_aborts_instead_of_buffering_the_whole_body():
    """The point of the fix.

    A 500MB body against a 10MB cap must cost ~10MB, not 500MB. If this ever
    regresses to `await file.read()` the assertion below fails loudly rather
    than the limit quietly becoming decorative again.
    """
    huge = 500 * 1024 * 1024
    cap = 10 * 1024 * 1024
    f = FakeUpload(huge)

    with pytest.raises(FileTooLarge):
        asyncio.run(read_upload_capped(f, cap))

    # Allow one chunk of overshoot — the cap is detected on the chunk that
    # crosses it — but nothing remotely like the full body.
    assert f.bytes_served <= cap + 64 * 1024
    assert f.bytes_served < huge / 10


def test_the_error_reports_the_limit_in_megabytes():
    f = FakeUpload(20 * 1024 * 1024)
    with pytest.raises(FileTooLarge) as exc:
        asyncio.run(read_upload_capped(f, 10 * 1024 * 1024))
    assert exc.value.max_mb == 10
    assert exc.value.http_status == 413


def test_a_zero_budget_refuses_immediately():
    """Reached in bulk upload once the batch budget is spent — the next file
    must not be read at all."""
    f = FakeUpload(1024)
    with pytest.raises(FileTooLarge):
        asyncio.run(read_upload_capped(f, 0))


def test_an_empty_upload_returns_empty_rather_than_hanging():
    f = FakeUpload(0)
    assert asyncio.run(read_upload_capped(f, 10 * 1024 * 1024)) == b""


class TestCallSitesUseTheGuard:
    """A guard nothing calls is not a guard."""

    def test_single_upload_does_not_use_a_bare_read(self):
        import inspect
        from app.api.v1.endpoints import analysis

        src = inspect.getsource(analysis.upload_resume)
        assert "read_upload_capped" in src
        assert "await file.read()" not in src

    def test_bulk_upload_spends_a_shared_batch_budget(self):
        import inspect
        from app.api.v1.endpoints import bulk

        src = inspect.getsource(bulk.bulk_upload)
        assert "read_upload_capped" in src
        assert "await f.read()" not in src
        # The budget must shrink as files are read, or 50 files each just
        # under the per-file cap still blow past the batch total.
        assert "batch_budget - total_bytes" in src

    def test_ats_import_does_not_use_a_bare_read(self):
        import inspect
        from app.api.v1.endpoints import ats

        src = inspect.getsource(ats.ats_import)
        assert "read_upload_capped" in src
        assert "await file.read()" not in src
