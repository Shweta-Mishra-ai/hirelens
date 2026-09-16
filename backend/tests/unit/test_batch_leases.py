"""
HireLens — Concurrent-batch slot leases

A user may have BULK_MAX_CONCURRENT_BATCHES_PER_USER batches running at once.
The slot is normally handed back when the batch's runner finishes, but a runner
that dies with the process never gets to — and on a free-tier container that
happens on every deploy and every wake from sleep. These cover the lease that
reclaims the slot anyway.

Run: cd backend && python -m pytest tests/unit/test_batch_leases.py -v
"""
import time
import pytest

from app.core.config import settings
from app.services.queue import batch_store


@pytest.fixture(autouse=True)
def clean_store():
    batch_store._mem_batches.clear()
    batch_store._mem_leases.clear()
    yield
    batch_store._mem_batches.clear()
    batch_store._mem_leases.clear()


class FakeRedis:
    """Enough of a Redis to exercise the lease path: a string store plus one
    sorted set per key, with the three commands the store actually issues."""

    def __init__(self, fail=False):
        self.fail = fail
        self.strings: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    def _guard(self):
        if self.fail:
            raise ConnectionError("redis down")

    def set(self, key, value, ex=None):
        self._guard()
        self.strings[key] = value

    def get(self, key):
        self._guard()
        return self.strings.get(key)

    def expire(self, key, seconds):
        self._guard()

    def zadd(self, key, mapping):
        self._guard()
        self.zsets.setdefault(key, {}).update(mapping)

    def zrem(self, key, member):
        self._guard()
        self.zsets.get(key, {}).pop(member, None)

    def zcard(self, key):
        self._guard()
        return len(self.zsets.get(key, {}))

    def zremrangebyscore(self, key, low, high):
        self._guard()
        members = self.zsets.get(key, {})
        for m in [m for m, score in members.items() if low <= score <= high]:
            members.pop(m)


# ── In-memory path ──────────────────────────────────────────────────────────
class TestMemoryLeases:
    def test_a_created_batch_holds_a_slot(self):
        batch_store.create_batch(None, "b1", "u1", ["j1"], total=1)
        assert batch_store.count_active_batches(None, "u1") == 1

    def test_releasing_frees_the_slot(self):
        batch_store.create_batch(None, "b1", "u1", ["j1"], total=1)
        batch_store.release_batch(None, "u1", "b1")
        assert batch_store.count_active_batches(None, "u1") == 0

    def test_slots_are_per_user(self):
        batch_store.create_batch(None, "b1", "u1", ["j1"], total=1)
        batch_store.create_batch(None, "b2", "u2", ["j2"], total=1)
        assert batch_store.count_active_batches(None, "u1") == 1
        assert batch_store.count_active_batches(None, "u2") == 1

    def test_an_abandoned_batch_stops_counting_once_its_lease_expires(self):
        """
        The bug: a slot was only ever freed by the runner's `finally`. Kill the
        process mid-batch and the slot was held until the key expired — six
        hours — so two interrupted batches locked a user out of bulk upload for
        the rest of the working day.
        """
        batch_store.create_batch(None, "b1", "u1", ["j1"], total=1)
        assert batch_store.count_active_batches(None, "u1") == 1

        # Age the lease past its lifetime, as a restart mid-batch would.
        batch_store._mem_leases["u1"]["b1"] -= settings.BATCH_LEASE_SECONDS + 1
        assert batch_store.count_active_batches(None, "u1") == 0

    def test_a_running_batch_keeps_its_slot_for_the_whole_lease(self):
        """A long batch must not have its slot pulled out from under it: 50
        files at BULK_CONCURRENCY=3 is over half an hour of real work."""
        batch_store.create_batch(None, "b1", "u1", ["j1"], total=50)
        batch_store._mem_leases["u1"]["b1"] -= settings.BATCH_LEASE_SECONDS - 60
        assert batch_store.count_active_batches(None, "u1") == 1

    def test_unknown_user_holds_nothing(self):
        assert batch_store.count_active_batches(None, "nobody") == 0

    def test_releasing_twice_is_harmless(self):
        batch_store.create_batch(None, "b1", "u1", ["j1"], total=1)
        batch_store.release_batch(None, "u1", "b1")
        batch_store.release_batch(None, "u1", "b1")
        assert batch_store.count_active_batches(None, "u1") == 0

    def test_user_entries_do_not_accumulate(self):
        """Every distinct user used to leave an entry behind for the life of
        the process, whether or not they still held a slot."""
        for i in range(50):
            batch_store.create_batch(None, f"b{i}", f"u{i}", ["j"], total=1)
            batch_store.release_batch(None, f"u{i}", f"b{i}")
        assert batch_store._mem_leases == {}

    def test_cleanup_drops_expired_leases(self):
        batch_store.create_batch(None, "b1", "u1", ["j1"], total=1)
        batch_store._mem_leases["u1"]["b1"] -= settings.BATCH_LEASE_SECONDS + 1
        batch_store.cleanup_old_batches()
        assert "u1" not in batch_store._mem_leases

    def test_cleanup_keeps_live_leases(self):
        batch_store.create_batch(None, "b1", "u1", ["j1"], total=1)
        batch_store.cleanup_old_batches()
        assert batch_store.count_active_batches(None, "u1") == 1


# ── Redis path ──────────────────────────────────────────────────────────────
class TestRedisLeases:
    def test_a_created_batch_holds_a_slot(self):
        redis = FakeRedis()
        batch_store.create_batch(redis, "b1", "u1", ["j1"], total=1)
        assert batch_store.count_active_batches(redis, "u1") == 1

    def test_releasing_frees_the_slot(self):
        redis = FakeRedis()
        batch_store.create_batch(redis, "b1", "u1", ["j1"], total=1)
        batch_store.release_batch(redis, "u1", "b1")
        assert batch_store.count_active_batches(redis, "u1") == 0

    def test_a_slot_survives_the_process_that_created_it(self):
        """Redis is the whole reason the slot is tracked outside the process —
        the limit has to hold across the two containers a deploy overlaps."""
        redis = FakeRedis()
        batch_store.create_batch(redis, "b1", "u1", ["j1"], total=1)

        # A fresh container: same Redis, empty memory.
        batch_store._mem_batches.clear()
        batch_store._mem_leases.clear()

        assert batch_store.count_active_batches(redis, "u1") == 1

    def test_an_abandoned_slot_is_reclaimed_after_its_lease(self):
        redis = FakeRedis()
        batch_store.create_batch(redis, "b1", "u1", ["j1"], total=1)
        batch_store._mem_batches.clear()
        batch_store._mem_leases.clear()

        # The runner died with its container, so nothing ever released it.
        redis.zsets[batch_store._lease_key("u1")]["b1"] -= settings.BATCH_LEASE_SECONDS + 1

        assert batch_store.count_active_batches(redis, "u1") == 0

    def test_redis_outage_falls_back_to_memory_rather_than_dropping_the_limit(self):
        """If the Redis count is unavailable the limit must still be enforced
        from what this process knows, not silently reported as zero."""
        redis = FakeRedis()
        batch_store.create_batch(redis, "b1", "u1", ["j1"], total=1)
        redis.fail = True
        assert batch_store.count_active_batches(redis, "u1") == 1

    def test_a_failed_persist_still_leaves_the_slot_held_in_memory(self):
        redis = FakeRedis(fail=True)
        batch_store.create_batch(redis, "b1", "u1", ["j1"], total=1)
        assert batch_store.count_active_batches(redis, "u1") == 1

    def test_the_larger_of_the_two_counts_wins(self):
        redis = FakeRedis()
        # One batch known only to Redis (started by another container), one
        # known only to memory (its Redis write failed).
        redis.zsets[batch_store._lease_key("u1")] = {"remote-a": time.time(), "remote-b": time.time()}
        batch_store._mem_leases["u1"] = {"local-a": time.time()}
        assert batch_store.count_active_batches(redis, "u1") == 2

    def test_lease_key_is_distinct_from_the_old_set_key(self):
        """The old key holds a SET in any deployment still running; issuing a
        sorted-set command against it would fail with WRONGTYPE."""
        assert batch_store._lease_key("u1") != "hirelens:active_batches:u1"

    def test_batch_record_is_still_readable_after_a_restart(self):
        redis = FakeRedis()
        batch_store.create_batch(redis, "b1", "u1", ["j1", "j2"], total=2)
        batch_store._mem_batches.clear()

        found = batch_store.get_batch(redis, "b1")
        assert found is not None
        assert found["user_id"] == "u1"
        assert found["job_ids"] == ["j1", "j2"]
