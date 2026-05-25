"""Tests for netweaver/leases.py — File Lease System.

Covers:
- FileLease data model (creation, serialization, expiration)
- LeaseManager acquire/release/renew lifecycle
- Conflict detection between agents
- Expired lease reclamation
- Persistence (save/load round-trip)
- Edge cases (empty paths, same-agent stacking, renew expired)
"""

import json
import os
import tempfile
import time
import pytest

from netweaver.leases import (
    FileLease,
    LeaseConflictError,
    LeaseExpiredError,
    LeaseManager,
    LeaseNotFoundError,
    _now_iso,
)


# ── FileLease unit tests ──


class TestFileLease:
    """FileLease data model tests."""

    def test_create_basic(self):
        lease = FileLease(
            lease_id="abc123",
            agent_id="runtime",
            file_paths={"a.py", "b.py"},
            acquired_at=_now_iso(),
            ttl_seconds=300,
        )
        assert lease.lease_id == "abc123"
        assert lease.agent_id == "runtime"
        assert lease.file_paths == {"a.py", "b.py"}
        assert lease.task_id is None
        assert lease.metadata == {}

    def test_create_with_task_and_metadata(self):
        lease = FileLease(
            lease_id="x",
            agent_id="wnal",
            file_paths={"wnal.py"},
            acquired_at=_now_iso(),
            ttl_seconds=60,
            task_id="NW-002",
            metadata={"priority": "high"},
        )
        assert lease.task_id == "NW-002"
        assert lease.metadata == {"priority": "high"}

    def test_serialization_round_trip(self):
        lease = FileLease(
            lease_id="roundtrip",
            agent_id="architect",
            file_paths={"scene.py", "graph.py"},
            acquired_at="2026-05-23T12:00:00+00:00",
            ttl_seconds=120,
            task_id="NW-004",
            metadata={"scope": "schema"},
        )
        d = lease.to_dict()
        # file_paths sorted
        assert d["file_paths"] == ["graph.py", "scene.py"]
        assert d["agent_id"] == "architect"

        restored = FileLease.from_dict(d)
        assert restored.lease_id == lease.lease_id
        assert restored.agent_id == lease.agent_id
        assert restored.file_paths == lease.file_paths
        assert restored.acquired_at == lease.acquired_at
        assert restored.ttl_seconds == lease.ttl_seconds
        assert restored.task_id == lease.task_id
        assert restored.metadata == lease.metadata

    def test_from_dict_string_paths(self):
        """from_dict handles a single string for file_paths."""
        d = {
            "lease_id": "s",
            "agent_id": "a",
            "file_paths": "single.py",
            "acquired_at": _now_iso(),
            "ttl_seconds": 30,
        }
        lease = FileLease.from_dict(d)
        assert lease.file_paths == {"single.py"}

    def test_is_expired_false(self):
        lease = FileLease(
            lease_id="fresh",
            agent_id="a",
            file_paths={"x"},
            acquired_at=_now_iso(),
            ttl_seconds=300,
        )
        assert not lease.is_expired()

    def test_is_expired_true(self):
        past = "2020-01-01T00:00:00+00:00"
        lease = FileLease(
            lease_id="old",
            agent_id="a",
            file_paths={"x"},
            acquired_at=past,
            ttl_seconds=60,
        )
        assert lease.is_expired()

    def test_is_expired_with_explicit_now(self):
        acquired = _now_iso()
        lease = FileLease(
            lease_id="timed",
            agent_id="a",
            file_paths={"x"},
            acquired_at=acquired,
            ttl_seconds=100,
        )
        # 50 seconds later → not expired
        from datetime import datetime, timezone
        base_ts = datetime.fromisoformat(acquired).timestamp()
        assert not lease.is_expired(now=base_ts + 50)
        # 101 seconds later → expired
        assert lease.is_expired(now=base_ts + 101)

    def test_remaining_seconds(self):
        acquired = _now_iso()
        lease = FileLease(
            lease_id="rem",
            agent_id="a",
            file_paths={"x"},
            acquired_at=acquired,
            ttl_seconds=100,
        )
        from datetime import datetime, timezone
        base_ts = datetime.fromisoformat(acquired).timestamp()
        remaining = lease.remaining_seconds(now=base_ts + 30)
        assert abs(remaining - 70) < 1

    def test_remaining_seconds_expired(self):
        lease = FileLease(
            lease_id="gone",
            agent_id="a",
            file_paths={"x"},
            acquired_at="2020-01-01T00:00:00+00:00",
            ttl_seconds=10,
        )
        assert lease.remaining_seconds() == 0.0

    def test_covers_path(self):
        lease = FileLease(
            lease_id="cov",
            agent_id="a",
            file_paths={"foo.py", "bar.py"},
            acquired_at=_now_iso(),
            ttl_seconds=60,
        )
        assert lease.covers_path("foo.py")
        assert lease.covers_path("bar.py")
        assert not lease.covers_path("baz.py")

    def test_empty_file_paths(self):
        lease = FileLease(
            lease_id="empty",
            agent_id="a",
            file_paths=set(),
            acquired_at=_now_iso(),
            ttl_seconds=60,
        )
        assert not lease.covers_path("anything")
        d = lease.to_dict()
        assert d["file_paths"] == []


# ── LeaseManager acquire/release/renew ──


class TestLeaseManagerAcquire:
    """Lease acquisition tests."""

    def test_acquire_basic(self):
        mgr = LeaseManager()
        lease = mgr.acquire("runtime", {"executor.py"}, ttl_seconds=60)
        assert lease.agent_id == "runtime"
        assert lease.covers_path("executor.py")
        assert lease.lease_id in mgr.leases

    def test_acquire_with_task_id(self):
        mgr = LeaseManager()
        lease = mgr.acquire("wnal", {"wnal.py"}, task_id="NW-002")
        assert lease.task_id == "NW-002"

    def test_acquire_with_metadata(self):
        mgr = LeaseManager()
        lease = mgr.acquire("qa", {"bench.py"}, metadata={"run": "1"})
        assert lease.metadata == {"run": "1"}

    def test_acquire_multiple_paths(self):
        mgr = LeaseManager()
        paths = {"a.py", "b.py", "c.py"}
        lease = mgr.acquire("runtime", paths)
        assert lease.file_paths == paths

    def test_acquire_same_agent_same_paths_stacks(self):
        """Same agent can acquire overlapping paths without conflict."""
        mgr = LeaseManager()
        l1 = mgr.acquire("runtime", {"a.py", "b.py"})
        l2 = mgr.acquire("runtime", {"b.py", "c.py"})
        assert l1.lease_id != l2.lease_id
        assert len(mgr.leases) == 2

    def test_acquire_different_agent_conflict_raises(self):
        mgr = LeaseManager()
        mgr.acquire("runtime", {"shared.py"})
        with pytest.raises(LeaseConflictError) as exc_info:
            mgr.acquire("architect", {"shared.py"})
        assert "runtime" in str(exc_info.value)
        assert len(mgr.leases) == 1

    def test_acquire_partial_overlap_conflict(self):
        mgr = LeaseManager()
        mgr.acquire("runtime", {"a.py", "b.py"})
        with pytest.raises(LeaseConflictError):
            mgr.acquire("wnal", {"b.py", "c.py"})

    def test_acquire_conflict_after_expiry(self):
        """Expired lease should be reclaimed, allowing new acquire."""
        mgr = LeaseManager()
        lease = mgr.acquire(
            "runtime", {"target.py"}, ttl_seconds=0.01
        )
        time.sleep(0.02)
        # Should succeed — old lease expired and reclaimed
        l2 = mgr.acquire("architect", {"target.py"})
        assert l2.agent_id == "architect"
        # Old lease should have been reclaimed
        assert lease.lease_id not in mgr.leases


class TestLeaseManagerRelease:
    """Lease release tests."""

    def test_release_basic(self):
        mgr = LeaseManager()
        lease = mgr.acquire("runtime", {"x.py"})
        mgr.release(lease.lease_id)
        assert len(mgr.leases) == 0

    def test_release_nonexistent_raises(self):
        mgr = LeaseManager()
        with pytest.raises(LeaseNotFoundError):
            mgr.release("nonexistent")

    def test_release_one_of_many(self):
        mgr = LeaseManager()
        l1 = mgr.acquire("a", {"x.py"})
        l2 = mgr.acquire("b", {"y.py"})
        mgr.release(l1.lease_id)
        assert l2.lease_id in mgr.leases
        assert l1.lease_id not in mgr.leases


class TestLeaseManagerRenew:
    """Lease renewal tests."""

    def test_renew_resets_timer(self):
        mgr = LeaseManager()
        lease = mgr.acquire("runtime", {"x.py"}, ttl_seconds=60)
        old_acquired = lease.acquired_at
        time.sleep(0.01)
        renewed = mgr.renew(lease.lease_id)
        assert renewed.acquired_at != old_acquired
        assert renewed.ttl_seconds == 60  # unchanged

    def test_renew_with_additional_ttl(self):
        mgr = LeaseManager()
        lease = mgr.acquire("runtime", {"x.py"}, ttl_seconds=60)
        renewed = mgr.renew(lease.lease_id, additional_ttl=120)
        assert renewed.ttl_seconds == 180

    def test_renew_nonexistent_raises(self):
        mgr = LeaseManager()
        with pytest.raises(LeaseNotFoundError):
            mgr.renew("ghost")

    def test_renew_expired_raises(self):
        mgr = LeaseManager()
        lease = mgr.acquire(
            "runtime", {"x.py"}, ttl_seconds=0.01
        )
        time.sleep(0.02)
        with pytest.raises(LeaseExpiredError):
            mgr.renew(lease.lease_id)


# ── Query operations ──


class TestLeaseManagerQuery:
    """Query and listing tests."""

    def test_list_active(self):
        mgr = LeaseManager()
        l1 = mgr.acquire("a", {"x.py"}, ttl_seconds=300)
        l2 = mgr.acquire("b", {"y.py"}, ttl_seconds=0.01)
        time.sleep(0.02)
        active = mgr.list_active()
        assert len(active) == 1
        assert active[0].lease_id == l1.lease_id

    def test_list_expired(self):
        mgr = LeaseManager()
        mgr.acquire("a", {"x.py"}, ttl_seconds=300)
        mgr.acquire("b", {"y.py"}, ttl_seconds=0.01)
        time.sleep(0.02)
        expired = mgr.list_expired()
        assert len(expired) == 1

    def test_list_by_agent(self):
        mgr = LeaseManager()
        mgr.acquire("runtime", {"a.py"})
        mgr.acquire("runtime", {"b.py"})
        mgr.acquire("architect", {"c.py"})
        runtime_leases = mgr.list_by_agent("runtime")
        assert len(runtime_leases) == 2

    def test_list_by_task(self):
        mgr = LeaseManager()
        mgr.acquire("a", {"x.py"}, task_id="NW-001")
        mgr.acquire("b", {"y.py"}, task_id="NW-002")
        mgr.acquire("c", {"z.py"}, task_id="NW-001")
        nw001 = mgr.list_by_task("NW-001")
        assert len(nw001) == 2

    def test_find_for_path(self):
        mgr = LeaseManager()
        l1 = mgr.acquire("a", {"x.py", "y.py"})
        l2 = mgr.acquire("b", {"z.py"})
        found = mgr.find_for_path("x.py")
        assert len(found) == 1
        assert found[0].lease_id == l1.lease_id

    def test_find_for_path_active_only(self):
        mgr = LeaseManager()
        mgr.acquire("a", {"x.py"}, ttl_seconds=0.01)
        time.sleep(0.02)
        assert len(mgr.find_for_path("x.py", active_only=True)) == 0
        assert len(mgr.find_for_path("x.py", active_only=False)) == 1

    def test_check_available_true(self):
        mgr = LeaseManager()
        available, conflicts = mgr.check_available({"free.py"})
        assert available
        assert conflicts == []

    def test_check_available_false(self):
        mgr = LeaseManager()
        mgr.acquire("runtime", {"taken.py"})
        available, conflicts = mgr.check_available({"taken.py"})
        assert not available
        assert len(conflicts) == 1

    def test_check_available_reclaims_expired(self):
        mgr = LeaseManager()
        mgr.acquire("runtime", {"old.py"}, ttl_seconds=0.01)
        time.sleep(0.02)
        available, _ = mgr.check_available({"old.py"})
        assert available


# ── Reclamation ──


class TestLeaseManagerReclaim:
    """Expired lease reclamation tests."""

    def test_reclaim_removes_expired(self):
        mgr = LeaseManager()
        mgr.acquire("a", {"x.py"}, ttl_seconds=0.01)
        mgr.acquire("b", {"y.py"}, ttl_seconds=300)
        time.sleep(0.02)
        count = mgr.reclaim_expired()
        assert count == 1
        assert len(mgr.leases) == 1

    def test_reclaim_nothing_if_all_active(self):
        mgr = LeaseManager()
        mgr.acquire("a", {"x.py"}, ttl_seconds=300)
        count = mgr.reclaim_expired()
        assert count == 0

    def test_reclaim_all_expired(self):
        mgr = LeaseManager()
        mgr.acquire("a", {"x.py"}, ttl_seconds=0.01)
        mgr.acquire("b", {"y.py"}, ttl_seconds=0.01)
        time.sleep(0.02)
        count = mgr.reclaim_expired()
        assert count == 2
        assert len(mgr.leases) == 0


# ── Persistence ──


class TestLeaseManagerPersistence:
    """Save/load round-trip tests."""

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "leases.json")
            mgr1 = LeaseManager(store_path=path)
            mgr1.acquire("runtime", {"a.py", "b.py"}, task_id="NW-001")
            mgr1.acquire("architect", {"scene.py"}, ttl_seconds=120)

            # Load from same file
            mgr2 = LeaseManager(store_path=path)
            assert len(mgr2.leases) == 2
            found = mgr2.find_for_path("a.py")
            assert len(found) == 1
            assert found[0].agent_id == "runtime"

    def test_save_atomic(self):
        """Verify no partial writes via tmp+rename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "leases.json")
            mgr = LeaseManager(store_path=path)
            mgr.acquire("a", {"x.py"})

            with open(path) as f:
                data = json.load(f)
            assert data["version"] == 1
            assert "leases" in data

    def test_load_corrupt_file(self):
        """Corrupt JSON should not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "leases.json")
            with open(path, "w") as f:
                f.write("NOT JSON")
            mgr = LeaseManager(store_path=path)
            assert len(mgr.leases) == 0

    def test_load_missing_fields(self):
        """Lease with missing required fields is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "leases.json")
            with open(path, "w") as f:
                json.dump({
                    "version": 1,
                    "leases": {
                        "bad": {"agent_id": "x"},  # missing fields
                    },
                }, f)
            mgr = LeaseManager(store_path=path)
            assert len(mgr.leases) == 0

    def test_to_dict(self):
        mgr = LeaseManager()
        mgr.acquire("runtime", {"x.py"})
        d = mgr.to_dict()
        assert d["version"] == 1
        assert d["lease_count"] == 1
        assert d["active_count"] == 1
        assert "leases" in d


# ── Edge cases ──


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_acquire_empty_paths(self):
        mgr = LeaseManager()
        lease = mgr.acquire("a", set())
        assert lease.file_paths == set()
        assert lease.covers_path("anything.py") is False

    def test_no_store_path(self):
        """Manager works without persistence."""
        mgr = LeaseManager()
        mgr.acquire("a", {"x.py"})
        mgr.release(list(mgr.leases.keys())[0])
        assert len(mgr.leases) == 0

    def test_lease_id_uniqueness(self):
        mgr = LeaseManager()
        ids = set()
        for _ in range(50):
            lease = mgr.acquire("a", {f"file_{_}.py"})
            ids.add(lease.lease_id)
        assert len(ids) == 50

    def test_conflict_error_has_details(self):
        mgr = LeaseManager()
        mgr.acquire("runtime", {"shared.py"})
        with pytest.raises(LeaseConflictError) as exc_info:
            mgr.acquire("architect", {"shared.py", "new.py"})
        err = exc_info.value
        assert len(err.conflicting_leases) > 0
        assert "shared.py" in err.requested_paths

    def test_get_lease(self):
        mgr = LeaseManager()
        lease = mgr.acquire("a", {"x.py"})
        retrieved = mgr.get(lease.lease_id)
        assert retrieved.lease_id == lease.lease_id

    def test_get_nonexistent_raises(self):
        mgr = LeaseManager()
        with pytest.raises(LeaseNotFoundError):
            mgr.get("ghost")

    def test_acquire_releases_expired_before_conflict_check(self):
        """Expired leases from another agent should be reclaimed before
        conflict detection, allowing the new acquire to succeed."""
        mgr = LeaseManager()
        mgr.acquire("runtime", {"x.py"}, ttl_seconds=0.01)
        time.sleep(0.02)
        # Different agent, same path — should succeed after reclaim
        lease = mgr.acquire("architect", {"x.py"})
        assert lease.agent_id == "architect"

    def test_multiple_agents_different_paths_no_conflict(self):
        mgr = LeaseManager()
        mgr.acquire("runtime", {"executor.py"})
        mgr.acquire("wnal", {"wnal.py"})
        mgr.acquire("qa", {"bench.py"})
        assert len(mgr.leases) == 3

    def test_release_and_reacquire(self):
        mgr = LeaseManager()
        l1 = mgr.acquire("runtime", {"x.py"})
        mgr.release(l1.lease_id)
        l2 = mgr.acquire("architect", {"x.py"})
        assert l2.agent_id == "architect"
