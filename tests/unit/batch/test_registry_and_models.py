"""Regression tests for BatchJobEntry.from_dict key-filtering (E-7) and
BatchRegistryManager.are_all_jobs_completed() lock-restructuring (E-8)."""

from __future__ import annotations

import threading

import pytest

from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_entry(**kwargs) -> BatchJobEntry:
    defaults = dict(
        batch_id="batch-abc",
        status="completed",
        timestamp="2024-01-01T00:00:00",
        provider="anthropic",
    )
    defaults.update(kwargs)
    return BatchJobEntry(**defaults)


def _make_registry(tmp_path) -> BatchRegistryManager:
    return BatchRegistryManager(tmp_path / ".batch_registry.json")


# ---------------------------------------------------------------------------
# E-7 — from_dict ignores unknown keys
# ---------------------------------------------------------------------------

class TestBatchJobEntryFromDict:
    """BatchJobEntry.from_dict() filters unknown keys rather than raising TypeError."""

    def test_round_trip_minimal(self):
        entry = _minimal_entry()
        result = BatchJobEntry.from_dict(entry.to_dict())
        assert result.batch_id == entry.batch_id
        assert result.status == entry.status

    def test_extra_key_is_dropped_not_raised(self):
        """Extra keys (e.g., from a future schema) must be silently dropped."""
        data = {
            "batch_id": "batch-xyz",
            "status": "completed",
            "timestamp": "2024-01-01T00:00:00",
            "provider": "anthropic",
            "future_key": "should_be_ignored",
            "another_unknown": 42,
        }
        entry = BatchJobEntry.from_dict(data)
        assert entry.batch_id == "batch-xyz"
        assert not hasattr(entry, "future_key")

    def test_subset_of_known_fields_with_defaults(self):
        """Missing optional fields should use dataclass defaults (None)."""
        data = {
            "batch_id": "batch-min",
            "status": "in_progress",
            "timestamp": "2024-01-01T00:00:00",
            "provider": "anthropic",
        }
        entry = BatchJobEntry.from_dict(data)
        assert entry.record_count is None
        assert entry.file_name is None


# ---------------------------------------------------------------------------
# E-8 — are_all_jobs_completed() branch coverage
# ---------------------------------------------------------------------------

class TestAreAllJobsCompleted:
    """are_all_jobs_completed() covers: empty cache, no-provider fast path,
    provider status update, provider exception fast-return, and re-acquire guard."""

    def test_empty_cache_returns_true(self, tmp_path):
        """No jobs → all complete."""
        mgr = _make_registry(tmp_path)
        assert mgr.are_all_jobs_completed() is True

    def test_no_provider_all_terminal_returns_true(self, tmp_path):
        """No provider; all terminal → True without any I/O."""
        mgr = _make_registry(tmp_path)
        mgr.save_batch_job("f1.json", _minimal_entry(status="completed"))
        mgr.save_batch_job("f2.json", _minimal_entry(batch_id="b2", status="failed"))
        assert mgr.are_all_jobs_completed() is True

    def test_no_provider_non_terminal_returns_false(self, tmp_path):
        """No provider; non-terminal job → False."""
        mgr = _make_registry(tmp_path)
        mgr.save_batch_job("f1.json", _minimal_entry(status="in_progress"))
        assert mgr.are_all_jobs_completed() is False

    def test_provider_updates_status_and_returns_true(self, tmp_path):
        """Provider returns terminal status → entry updated, returns True."""
        mgr = _make_registry(tmp_path)
        mgr.save_batch_job("f1.json", _minimal_entry(status="in_progress"))

        def check_provider(batch_id: str) -> str:
            return "completed"

        assert mgr.are_all_jobs_completed(check_provider=check_provider) is True
        # Verify the update was persisted to cache
        entry = mgr.get_batch_job("f1.json")
        assert entry is not None
        assert entry.status == "completed"

    def test_provider_exception_returns_false(self, tmp_path):
        """If check_provider raises, method returns False (safe degradation)."""
        mgr = _make_registry(tmp_path)
        mgr.save_batch_job("f1.json", _minimal_entry(status="in_progress"))

        def failing_provider(batch_id: str) -> str:
            raise ConnectionError("network down")

        result = mgr.are_all_jobs_completed(check_provider=failing_provider)
        assert result is False

    def test_provider_not_called_for_terminal_entries(self, tmp_path):
        """check_provider must only be called for non-terminal entries."""
        mgr = _make_registry(tmp_path)
        mgr.save_batch_job("f1.json", _minimal_entry(status="completed"))
        calls = []

        def spy_provider(batch_id: str) -> str:
            calls.append(batch_id)
            return "completed"

        mgr.are_all_jobs_completed(check_provider=spy_provider)
        assert calls == [], "provider should not be called for already-terminal entries"

    def test_concurrent_calls_do_not_deadlock(self, tmp_path):
        """Lock release before I/O prevents deadlock under concurrency."""
        mgr = _make_registry(tmp_path)
        mgr.save_batch_job("f1.json", _minimal_entry(status="in_progress"))

        results = []
        barrier = threading.Barrier(3)

        def check_provider(batch_id: str) -> str:
            barrier.wait(timeout=5)  # all threads reach I/O phase together
            return "completed"

        def worker():
            results.append(mgr.are_all_jobs_completed(check_provider=check_provider))

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(results) == 3, "all threads must complete without deadlock"
