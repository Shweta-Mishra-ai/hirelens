"""
HireLens — Bulk Upload (Feature 1) Unit Tests
Run: cd backend && python -m pytest tests/unit/test_bulk.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestBatchStore:
    def setup_method(self):
        from app.services.queue import batch_store
        # Isolate each test from module-level in-memory state
        batch_store._mem_batches.clear()
        batch_store._mem_active_batches_by_user.clear()
        self.store = batch_store

    def test_create_and_get_batch_no_redis(self):
        data = self.store.create_batch(None, "batch-1", "user-1", ["j1", "j2"], total=2)
        assert data["id"] == "batch-1"
        fetched = self.store.get_batch(None, "batch-1")
        assert fetched is not None
        assert fetched["job_ids"] == ["j1", "j2"]
        assert fetched["user_id"] == "user-1"

    def test_get_missing_batch_returns_none(self):
        assert self.store.get_batch(None, "does-not-exist") is None

    def test_active_batch_counter_tracks_and_releases(self):
        assert self.store.count_active_batches(None, "user-1") == 0
        self.store.create_batch(None, "batch-a", "user-1", ["j1"], total=1)
        assert self.store.count_active_batches(None, "user-1") == 1
        self.store.create_batch(None, "batch-b", "user-1", ["j2"], total=1)
        assert self.store.count_active_batches(None, "user-1") == 2
        self.store.release_batch(None, "user-1", "batch-a")
        assert self.store.count_active_batches(None, "user-1") == 1

    def test_batches_scoped_per_user(self):
        self.store.create_batch(None, "batch-x", "user-1", ["j1"], total=1)
        assert self.store.count_active_batches(None, "user-2") == 0


class TestRankingAndCSV:
    """Exercises the ranking/CSV logic in bulk.py using in-memory job data —
    no network, DB, or Redis required."""

    def setup_method(self):
        from app.api.v1.endpoints import analysis as analysis_mod
        from app.api.v1.endpoints import bulk as bulk_mod
        analysis_mod._jobs.clear()
        self.jobs = analysis_mod._jobs
        self.bulk = bulk_mod

        # Two completed jobs (different scores), one failed, one still running.
        self.jobs["job-hi"] = {
            "id": "job-hi", "status": "complete", "stage": "complete", "progress": 100,
            "file_name": "alice.pdf", "report_id": "rep-hi", "error": None,
        }
        self.jobs["report_rep-hi"] = {
            "candidate": {"name": "Alice High"},
            "credibility": {"overall": 91, "recommendation": "recommended"},
            "file_name": "alice.pdf",
        }
        self.jobs["job-lo"] = {
            "id": "job-lo", "status": "complete", "stage": "complete", "progress": 100,
            "file_name": "bob.pdf", "report_id": "rep-lo", "error": None,
        }
        self.jobs["report_rep-lo"] = {
            "candidate": {"name": "Bob Low"},
            "credibility": {"overall": 42, "recommendation": "high_risk"},
            "file_name": "bob.pdf",
        }
        self.jobs["job-failed"] = {
            "id": "job-failed", "status": "failed", "stage": "failed", "progress": 0,
            "file_name": "corrupt.pdf", "report_id": None, "error": "Could not read file",
        }
        self.jobs["job-running"] = {
            "id": "job-running", "status": "running", "stage": "extracting", "progress": 40,
            "file_name": "carol.pdf", "report_id": None, "error": None,
        }

        self.batch = {
            "id": "batch-1", "user_id": "user-1",
            "job_ids": ["job-hi", "job-lo", "job-failed", "job-running"],
            "total": 4,
        }

    def test_ranking_sorted_by_score_desc(self):
        result = self.bulk._build_status_and_ranking(self.batch, db=None)
        scores = [r["overall_score"] for r in result["ranking"]]
        assert scores == sorted(scores, reverse=True)
        assert result["ranking"][0]["candidate_name"] == "Alice High"
        assert result["ranking"][0]["rank"] == 1

    def test_counts_and_is_done(self):
        result = self.bulk._build_status_and_ranking(self.batch, db=None)
        assert result["complete"] == 2
        assert result["failed"] == 1
        assert result["running"] == 1
        assert result["is_done"] is False  # 3/4 terminal, 1 still running

    def test_failed_and_running_jobs_excluded_from_ranking(self):
        result = self.bulk._build_status_and_ranking(self.batch, db=None)
        names = [r["candidate_name"] for r in result["ranking"]]
        assert "corrupt.pdf" not in names
        assert len(result["ranking"]) == 2

    def test_csv_export_contains_ranked_rows(self):
        import csv
        import io
        result = self.bulk._build_status_and_ranking(self.batch, db=None)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Rank", "Candidate Name", "File Name", "Score", "Recommendation", "Report ID"])
        for r in result["ranking"]:
            writer.writerow([r["rank"], r["candidate_name"], r["file_name"], r["overall_score"], r["recommendation"], r["report_id"]])

        buf.seek(0)
        rows = list(csv.reader(buf))
        assert rows[0][0] == "Rank"
        assert rows[1][1] == "Alice High"
        assert rows[2][1] == "Bob Low"
