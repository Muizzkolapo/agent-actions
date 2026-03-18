"""Tests for BatchRegistryManager — thread-safe registry with persistence."""

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    batch_id: str = "batch-001",
    status: str = BatchStatus.SUBMITTED,
    provider: str = "openai",
    timestamp: str = "2026-01-01T00:00:00Z",
    **kwargs,
) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=batch_id,
        status=status,
        provider=provider,
        timestamp=timestamp,
        **kwargs,
    )


@pytest.fixture()
def registry_path(tmp_path: Path) -> Path:
    return tmp_path / ".batch_registry.json"


@pytest.fixture()
def manager(registry_path: Path) -> BatchRegistryManager:
    return BatchRegistryManager(registry_path)


# ---------------------------------------------------------------------------
# Registration and retrieval
# ---------------------------------------------------------------------------


class TestSaveAndGet:
    """Save entries and retrieve them by file name or batch ID."""

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_save_then_get_by_file_name(self, _fire, manager):
        entry = _make_entry()
        manager.save_batch_job("file_a.jsonl", entry)

        result = manager.get_batch_job("file_a.jsonl")
        assert result is not None
        assert result.batch_id == "batch-001"
        assert result.status == BatchStatus.SUBMITTED

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_save_then_get_by_batch_id(self, _fire, manager):
        entry = _make_entry(batch_id="batch-xyz")
        manager.save_batch_job("f.jsonl", entry)

        result = manager.get_batch_job_by_id("batch-xyz")
        assert result is not None
        assert result.batch_id == "batch-xyz"

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_get_all_jobs_returns_copy(self, _fire, manager):
        e1 = _make_entry(batch_id="b1")
        e2 = _make_entry(batch_id="b2")
        manager.save_batch_job("f1", e1)
        manager.save_batch_job("f2", e2)

        jobs = manager.get_all_jobs()
        assert len(jobs) == 2
        # Mutating the returned dict should not affect internal state.
        jobs.pop("f1")
        assert len(manager.get_all_jobs()) == 2

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_overwrite_existing_key(self, _fire, manager):
        """Saving a second entry with the same key overwrites the first."""
        manager.save_batch_job("f", _make_entry(batch_id="old"))
        manager.save_batch_job("f", _make_entry(batch_id="new"))

        result = manager.get_batch_job("f")
        assert result is not None
        assert result.batch_id == "new"
        assert len(manager.get_all_jobs()) == 1


# ---------------------------------------------------------------------------
# Edge cases — missing entries
# ---------------------------------------------------------------------------


class TestMissingEntries:
    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_get_missing_file_name_returns_none(self, _fire, manager):
        assert manager.get_batch_job("nonexistent") is None

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_get_missing_batch_id_returns_none(self, _fire, manager):
        assert manager.get_batch_job_by_id("no-such-id") is None

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_remove_missing_returns_false(self, _fire, manager):
        assert manager.remove_batch_job("ghost") is False

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_update_status_missing_returns_false(self, _fire, manager):
        assert manager.update_status("no-id", BatchStatus.COMPLETED) is False


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


class TestRemove:
    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_remove_existing_entry(self, _fire, manager):
        manager.save_batch_job("f", _make_entry())
        assert manager.remove_batch_job("f") is True
        assert manager.get_batch_job("f") is None

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_remove_nonexistent_entry(self, _fire, manager):
        assert manager.remove_batch_job("missing") is False


# ---------------------------------------------------------------------------
# Update status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_update_status_success(self, _fire, manager):
        manager.save_batch_job("f", _make_entry(batch_id="b1"))
        assert manager.update_status("b1", BatchStatus.COMPLETED) is True
        entry = manager.get_batch_job("f")
        assert entry is not None
        assert entry.status == BatchStatus.COMPLETED

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_update_status_not_found(self, _fire, manager):
        assert manager.update_status("missing", BatchStatus.FAILED) is False


# ---------------------------------------------------------------------------
# Persistence — save / load round-trip
# ---------------------------------------------------------------------------


class TestPersistence:
    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_round_trip_via_new_manager(self, _fire, registry_path):
        """Data written by one manager is readable by a fresh manager."""
        m1 = BatchRegistryManager(registry_path)
        m1.save_batch_job("f1", _make_entry(batch_id="b1", status=BatchStatus.COMPLETED))

        m2 = BatchRegistryManager(registry_path)
        entry = m2.get_batch_job("f1")
        assert entry is not None
        assert entry.batch_id == "b1"
        assert entry.status == BatchStatus.COMPLETED

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_load_empty_when_file_missing(self, _fire, tmp_path):
        """When registry file doesn't exist, cache starts empty."""
        m = BatchRegistryManager(tmp_path / "absent.json")
        assert m.get_all_jobs() == {}

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_load_corrupted_file_returns_empty(self, _fire, tmp_path):
        """Corrupted JSON on disk -> empty registry, no crash."""
        path = tmp_path / "reg.json"
        path.write_text("{invalid json!!!", encoding="utf-8")
        m = BatchRegistryManager(path)
        assert m.get_all_jobs() == {}

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_load_with_invalid_entry_skips_it(self, _fire, tmp_path):
        """An entry that fails BatchJobEntry.from_dict is skipped."""
        path = tmp_path / "reg.json"
        data = {
            "good": {
                "batch_id": "b1",
                "status": BatchStatus.SUBMITTED,
                "timestamp": "t",
                "provider": "p",
            },
            "bad": {"missing_required_fields": True},
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        m = BatchRegistryManager(path)
        jobs = m.get_all_jobs()
        assert len(jobs) == 1
        assert "good" in jobs

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_persist_creates_parent_directories(self, _fire, tmp_path):
        """Atomic write creates parent dirs if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "reg.json"
        m = BatchRegistryManager(deep_path)
        m.save_batch_job("f", _make_entry())
        assert deep_path.exists()


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


class TestCacheInvalidation:
    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_invalidate_forces_reload_from_disk(self, _fire, registry_path):
        m = BatchRegistryManager(registry_path)
        m.save_batch_job("f", _make_entry(batch_id="original"))

        # Tamper with the file directly — simulating external modification.
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
        raw["f"]["batch_id"] = "tampered"
        registry_path.write_text(json.dumps(raw), encoding="utf-8")

        # Before invalidation, cache still holds old data.
        assert manager_entry_id(m, "f") == "original"

        m.invalidate_cache()

        # After invalidation, next access reloads from disk.
        assert manager_entry_id(m, "f") == "tampered"


def manager_entry_id(m: BatchRegistryManager, key: str) -> str:
    entry = m.get_batch_job(key)
    assert entry is not None
    return entry.batch_id


# ---------------------------------------------------------------------------
# Registry stats & overall status
# ---------------------------------------------------------------------------


class TestRegistryStats:
    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_empty_registry_stats(self, _fire, manager):
        stats = manager.get_registry_stats()
        assert stats.total_jobs == 0
        assert stats.overall_status == "no_batches"

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_all_completed(self, _fire, manager):
        manager.save_batch_job("f1", _make_entry(batch_id="b1", status=BatchStatus.COMPLETED))
        manager.save_batch_job("f2", _make_entry(batch_id="b2", status=BatchStatus.COMPLETED))
        stats = manager.get_registry_stats()
        assert stats.completed == 2
        assert stats.total_jobs == 2
        assert stats.overall_status == "completed"

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_mixed_statuses(self, _fire, manager):
        manager.save_batch_job("f1", _make_entry(batch_id="b1", status=BatchStatus.COMPLETED))
        manager.save_batch_job("f2", _make_entry(batch_id="b2", status=BatchStatus.FAILED))
        manager.save_batch_job("f3", _make_entry(batch_id="b3", status=BatchStatus.IN_PROGRESS))
        manager.save_batch_job("f4", _make_entry(batch_id="b4", status=BatchStatus.CANCELLED))
        stats = manager.get_registry_stats()
        assert stats.total_jobs == 4
        assert stats.completed == 1
        assert stats.failed == 1
        assert stats.in_progress == 1
        assert stats.cancelled == 1


# ---------------------------------------------------------------------------
# are_all_jobs_completed
# ---------------------------------------------------------------------------


class TestAreAllJobsCompleted:
    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_empty_registry_is_all_completed(self, _fire, manager):
        assert manager.are_all_jobs_completed() is True

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_all_terminal(self, _fire, manager):
        manager.save_batch_job("f1", _make_entry(batch_id="b1", status=BatchStatus.COMPLETED))
        manager.save_batch_job("f2", _make_entry(batch_id="b2", status=BatchStatus.FAILED))
        assert manager.are_all_jobs_completed() is True

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_not_all_terminal(self, _fire, manager):
        manager.save_batch_job("f1", _make_entry(batch_id="b1", status=BatchStatus.COMPLETED))
        manager.save_batch_job("f2", _make_entry(batch_id="b2", status=BatchStatus.IN_PROGRESS))
        assert manager.are_all_jobs_completed() is False

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_check_provider_updates_status(self, _fire, manager):
        """When a check_provider is supplied, non-terminal entries get refreshed."""
        manager.save_batch_job("f", _make_entry(batch_id="b1", status=BatchStatus.IN_PROGRESS))

        def provider(bid):
            return BatchStatus.COMPLETED

        assert manager.are_all_jobs_completed(check_provider=provider) is True
        # Status should now be persisted as completed.
        entry = manager.get_batch_job("f")
        assert entry is not None
        assert entry.status == BatchStatus.COMPLETED

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_check_provider_error_returns_false(self, _fire, manager):
        """If check_provider raises, assume not complete."""
        manager.save_batch_job("f", _make_entry(batch_id="b1", status=BatchStatus.IN_PROGRESS))

        def failing_provider(bid):
            raise RuntimeError("API down")

        assert manager.are_all_jobs_completed(check_provider=failing_provider) is False


# ---------------------------------------------------------------------------
# Thread safety — concurrent access
# ---------------------------------------------------------------------------


class TestThreadSafety:
    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_concurrent_saves(self, _fire, registry_path):
        """Multiple threads saving concurrently must not corrupt the registry."""
        mgr = BatchRegistryManager(registry_path)
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        errors: list[Exception] = []

        def worker(idx: int):
            try:
                barrier.wait(timeout=5)
                entry = _make_entry(batch_id=f"batch-{idx}")
                mgr.save_batch_job(f"file-{idx}", entry)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"
        assert len(mgr.get_all_jobs()) == num_threads

    @patch("agent_actions.llm.batch.infrastructure.registry.fire_event")
    def test_concurrent_reads_and_writes(self, _fire, registry_path):
        """Mix of readers and writers should not raise or corrupt."""
        mgr = BatchRegistryManager(registry_path)
        # Pre-populate
        for i in range(5):
            mgr.save_batch_job(f"pre-{i}", _make_entry(batch_id=f"pre-{i}"))

        errors: list[Exception] = []

        def reader():
            try:
                for _ in range(10):
                    mgr.get_all_jobs()
                    mgr.get_batch_job("pre-0")
            except Exception as exc:
                errors.append(exc)

        def writer(idx: int):
            try:
                for j in range(5):
                    mgr.save_batch_job(f"w-{idx}-{j}", _make_entry(batch_id=f"w-{idx}-{j}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        threads += [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"Thread errors: {errors}"
