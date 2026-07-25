"""
HireLens — Persistent Job Store Tests
Run: cd backend && python -m pytest tests/unit/test_job_store.py -v

These specifically guard against the bug class this migration had to avoid:
in-place dict mutation (`store[k].update(...)` or `store[k]["x"] = y`)
silently bypassing Redis persistence because it never calls __setitem__.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.queue.job_store import PersistentJobStore


class FakeRedis:
    """In-process fake standing in for a real Redis connection — lets us
    assert on exactly what got persisted, byte for byte."""
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def delete(self, key):
        self.data.pop(key, None)
        self.ttls.pop(key, None)

    def exists(self, key):
        return key in self.data


class TestBasicDictAPI:
    def setup_method(self):
        self.redis = FakeRedis()
        self.store = PersistentJobStore(get_redis_fn=lambda: self.redis)

    def test_setitem_and_getitem(self):
        self.store["job-1"] = {"status": "queued"}
        assert self.store["job-1"] == {"status": "queued"}

    def test_contains(self):
        self.store["job-1"] = {"status": "queued"}
        assert "job-1" in self.store
        assert "job-missing" not in self.store

    def test_get_with_default(self):
        assert self.store.get("missing", "fallback") == "fallback"
        self.store["job-1"] = {"status": "queued"}
        assert self.store.get("job-1") == {"status": "queued"}

    def test_delitem(self):
        self.store["job-1"] = {"status": "queued"}
        del self.store["job-1"]
        assert "job-1" not in self.store

    def test_pop(self):
        self.store["job-1"] = {"status": "queued"}
        val = self.store.pop("job-1", None)
        assert val == {"status": "queued"}
        assert "job-1" not in self.store

    def test_pop_missing_returns_default(self):
        assert self.store.pop("nope", "default") == "default"

    def test_keyerror_on_missing_getitem(self):
        import pytest
        with pytest.raises(KeyError):
            self.store["does-not-exist"]


class TestRedisPersistence:
    """The whole point of this migration — every write must actually reach Redis."""

    def setup_method(self):
        self.redis = FakeRedis()
        self.store = PersistentJobStore(get_redis_fn=lambda: self.redis)

    def test_setitem_persists_to_redis(self):
        self.store["job-1"] = {"status": "running", "progress": 40}
        raw = self.redis.get("hirelens:store:job-1")
        assert raw is not None
        assert json.loads(raw) == {"status": "running", "progress": 40}

    def test_persists_with_ttl(self):
        self.store["job-1"] = {"status": "queued"}
        assert self.redis.ttls.get("hirelens:store:job-1") == 21_600

    def test_delitem_removes_from_redis(self):
        self.store["job-1"] = {"status": "queued"}
        del self.store["job-1"]
        assert self.redis.get("hirelens:store:job-1") is None

    def test_read_falls_through_to_redis_when_not_in_local_memory(self):
        """Simulates a fresh process (empty local cache) reading a job that
        was written before a restart — the exact scenario this migration
        exists to fix."""
        # Write directly to "Redis" as if a previous process wrote it
        self.redis.set("hirelens:store:job-1", json.dumps({"status": "complete", "report_id": "r1"}))
        fresh_store = PersistentJobStore(get_redis_fn=lambda: self.redis)  # simulates new process, empty local cache
        assert fresh_store["job-1"] == {"status": "complete", "report_id": "r1"}

    def test_reassignment_pattern_persists_correctly(self):
        """This is the exact fix pattern used at the analysis.py/bulk.py/
        match.py call sites: `store[k] = {**store[k], **updates}` instead of
        `store[k].update(updates)`. Prove it actually reaches Redis."""
        self.store["job-1"] = {"status": "queued", "progress": 0}
        # simulate the upd() helper's fixed pattern
        current = self.store["job-1"]
        self.store["job-1"] = {**current, "status": "running", "progress": 50}

        raw = json.loads(self.redis.get("hirelens:store:job-1"))
        assert raw["status"] == "running"
        assert raw["progress"] == 50

    def test_inplace_mutation_would_NOT_persist_demonstrating_why_fix_was_needed(self):
        """Documents the bug class this migration specifically avoided —
        mutating the dict object returned by __getitem__ directly does NOT
        trigger __setitem__, so it silently never reaches Redis. This test
        exists so nobody 'simplifies' a call site back into this pattern."""
        self.store["job-1"] = {"status": "queued"}
        got = self.store["job-1"]
        got["status"] = "running"  # in-place mutation — the bug pattern

        # Redis still has the OLD value because __setitem__ was never called
        raw = json.loads(self.redis.get("hirelens:store:job-1"))
        assert raw["status"] == "queued", (
            "If this fails, the store's internal caching changed in a way "
            "that could reintroduce silent persistence bugs elsewhere."
        )


class TestRedisFailureIsGraceful:
    """No Redis configured, or Redis errors — must never break the app."""

    def test_none_redis_behaves_as_pure_memory(self):
        store = PersistentJobStore(get_redis_fn=lambda: None)
        store["job-1"] = {"status": "queued"}
        assert store["job-1"] == {"status": "queued"}
        assert "job-1" in store
        del store["job-1"]
        assert "job-1" not in store

    def test_redis_getter_raising_does_not_crash_writes(self):
        def broken_redis():
            raise ConnectionError("redis unreachable")

        store = PersistentJobStore(get_redis_fn=broken_redis)
        store["job-1"] = {"status": "queued"}  # must not raise
        assert store["job-1"] == {"status": "queued"}  # local memory still works

    def test_redis_set_raising_does_not_crash_writes(self):
        class ExplodingRedis:
            def set(self, *a, **kw):
                raise ConnectionError("boom")
            def get(self, *a, **kw):
                raise ConnectionError("boom")
            def delete(self, *a, **kw):
                raise ConnectionError("boom")
            def exists(self, *a, **kw):
                raise ConnectionError("boom")

        store = PersistentJobStore(get_redis_fn=lambda: ExplodingRedis())
        store["job-1"] = {"status": "queued"}  # must not raise
        assert store["job-1"] == {"status": "queued"}  # served from local memory


class TestCleanupStale:
    def test_removes_entries_older_than_max_age(self):
        redis = FakeRedis()
        store = PersistentJobStore(get_redis_fn=lambda: redis)
        store["old-job"] = {"created_at": 1000}
        store["new-job"] = {"created_at": 99999999999}

        removed = store.cleanup_stale(max_age_seconds=10)
        assert removed == 1
        assert "old-job" not in store._mem
        assert "new-job" in store._mem

    def test_entries_without_created_at_are_kept(self):
        redis = FakeRedis()
        store = PersistentJobStore(get_redis_fn=lambda: redis)
        store["no-timestamp"] = {"status": "queued"}
        removed = store.cleanup_stale(max_age_seconds=10)
        assert removed == 0
