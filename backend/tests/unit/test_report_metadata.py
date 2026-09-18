"""
Tests for report metadata on the in-memory storage path.

Two fields were wrong here and both were visible to users:

* `file_name` — the writer stamped `_owner_file_name` while every reader
  looked for `file_name`, so the dashboard showed a blank filename for every
  report whenever the Supabase path wasn't taken, and filename search never
  matched.
* `created_at` — nothing set it. The list endpoint emitted `""` and the
  dashboard's relative-time formatter rendered that as the literal string
  "NaNd ago".
"""

from datetime import datetime, timezone

from app.api.v1.endpoints.analysis import _stamp_report_metadata
from app.api.v1.endpoints.reports import _mem_reports_for_user
from app.api.v1.endpoints.analysis import _jobs


def _stamped(**kw):
    base = {"candidate": {"name": "Priya Raghavan"}, "credibility": {"overall": 74, "recommendation": "manual_review"}}
    base.update(kw.pop("report", {}))
    return _stamp_report_metadata(
        base,
        user_id=kw.get("user_id", "user-1"),
        filename=kw.get("filename", "priya_resume.pdf"),
        report_id=kw.get("report_id", "rep-1"),
    )


def test_stamps_file_name_under_the_key_readers_use():
    r = _stamped()
    assert r["file_name"] == "priya_resume.pdf"


def test_still_stamps_the_legacy_key_for_older_blobs():
    r = _stamped()
    assert r["_owner_file_name"] == "priya_resume.pdf"


def test_stamps_a_parseable_iso_created_at():
    r = _stamped()
    parsed = datetime.fromisoformat(r["created_at"])
    assert parsed.tzinfo is not None, "created_at must be timezone-aware"
    delta = abs((datetime.now(timezone.utc) - parsed).total_seconds())
    assert delta < 60


def test_stamps_owner_and_id():
    r = _stamped(user_id="user-42", report_id="rep-42")
    assert r["_owner_user_id"] == "user-42"
    assert r["id"] == "rep-42"


class TestListing:
    def setup_method(self):
        _jobs.clear()

    def teardown_method(self):
        _jobs.clear()

    def test_listed_report_carries_file_name_and_created_at(self):
        _jobs["report_rep-1"] = _stamped(user_id="user-1", filename="priya_resume.pdf")
        rows = _mem_reports_for_user("user-1")
        assert len(rows) == 1
        assert rows[0]["file_name"] == "priya_resume.pdf"
        assert rows[0]["created_at"] != ""
        datetime.fromisoformat(rows[0]["created_at"])  # must not raise

    def test_legacy_blob_without_file_name_falls_back_to_owner_key(self):
        """A report persisted by an older build only has `_owner_file_name`."""
        _jobs["report_legacy"] = {
            "_owner_user_id": "user-1",
            "_owner_file_name": "old_resume.pdf",
            "candidate": {"name": "Old Candidate"},
            "credibility": {"overall": 60, "recommendation": "manual_review"},
        }
        rows = _mem_reports_for_user("user-1")
        assert rows[0]["file_name"] == "old_resume.pdf"

    def test_file_name_is_never_null(self):
        """
        The dashboard renders this directly; a null here reached the UI as a
        blank cell. An empty string is the contract, not None.
        """
        _jobs["report_nameless"] = {
            "_owner_user_id": "user-1",
            "candidate": {"name": "Nameless"},
            "credibility": {"overall": 50, "recommendation": "high_risk"},
        }
        rows = _mem_reports_for_user("user-1")
        assert rows[0]["file_name"] == ""
        assert rows[0]["file_name"] is not None

    def test_reports_remain_scoped_to_their_owner(self):
        _jobs["report_a"] = _stamped(user_id="user-1", report_id="a")
        _jobs["report_b"] = _stamped(user_id="user-2", report_id="b")
        assert len(_mem_reports_for_user("user-1")) == 1
        assert len(_mem_reports_for_user("user-2")) == 1
        assert _mem_reports_for_user("stranger") == []

    def test_unowned_blob_is_visible_to_nobody(self):
        _jobs["report_orphan"] = {"candidate": {"name": "Orphan"}, "credibility": {}}
        assert _mem_reports_for_user("user-1") == []
        assert _mem_reports_for_user("") == []
