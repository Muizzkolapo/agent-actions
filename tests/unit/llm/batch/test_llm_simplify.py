"""Tests for LLM simplify refactor: batch_id index, find_missing_ids, OnExhaustedPolicy."""

from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_constants import OnExhaustedPolicy
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler


def _entry(batch_id: str, status: str = "completed") -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=batch_id, status=status, timestamp="2026-01-01T00:00:00", provider="test"
    )


# -- batch_id index ----------------------------------------------------------


class TestBatchIdIndex:
    """Verify the batch_id -> file_name index stays coherent."""

    def test_index_built_on_first_access(self, tmp_path):
        mgr = BatchRegistryManager(tmp_path / "reg.json")
        mgr.save_batch_job("a.json", _entry("batch-1"))
        # Invalidate and re-load to force index rebuild from disk
        mgr.invalidate_cache()
        entry = mgr.get_batch_job_by_id("batch-1")
        assert entry is not None
        assert entry.batch_id == "batch-1"

    def test_overwrite_remaps_index(self, tmp_path):
        """When file_name gets a new batch_id, old batch_id should be evicted."""
        mgr = BatchRegistryManager(tmp_path / "reg.json")
        mgr.save_batch_job("a.json", _entry("batch-old"))
        mgr.save_batch_job("a.json", _entry("batch-new"))

        assert mgr.get_batch_job_by_id("batch-new") is not None
        assert mgr.get_batch_job_by_id("batch-old") is None

    def test_remove_clears_index(self, tmp_path):
        mgr = BatchRegistryManager(tmp_path / "reg.json")
        mgr.save_batch_job("a.json", _entry("batch-1"))
        mgr.remove_batch_job("a.json")
        assert mgr.get_batch_job_by_id("batch-1") is None

    def test_update_status_via_index(self, tmp_path):
        mgr = BatchRegistryManager(tmp_path / "reg.json")
        mgr.save_batch_job("a.json", _entry("batch-1", status="submitted"))
        assert mgr.update_status("batch-1", "completed") is True
        assert mgr.get_batch_job_by_id("batch-1").status == "completed"

    def test_update_status_not_found(self, tmp_path):
        mgr = BatchRegistryManager(tmp_path / "reg.json")
        mgr.save_batch_job("a.json", _entry("batch-1"))
        assert mgr.update_status("nonexistent", "completed") is False

    def test_invalidate_clears_index(self, tmp_path):
        mgr = BatchRegistryManager(tmp_path / "reg.json")
        mgr.save_batch_job("a.json", _entry("batch-1"))
        mgr.invalidate_cache()
        # After invalidation, next access rebuilds — should still find it
        assert mgr.get_batch_job_by_id("batch-1") is not None

    def test_save_remove_save_cycle(self, tmp_path):
        """Index stays consistent through save/remove/save cycles."""
        mgr = BatchRegistryManager(tmp_path / "reg.json")
        mgr.save_batch_job("a.json", _entry("batch-1"))
        mgr.remove_batch_job("a.json")
        mgr.save_batch_job("a.json", _entry("batch-2"))

        assert mgr.get_batch_job_by_id("batch-1") is None
        assert mgr.get_batch_job_by_id("batch-2") is not None


# -- find_missing_ids ---------------------------------------------------------


class TestFindMissingIds:
    """Verify BatchResultReconciler.find_missing_ids consolidation."""

    def _make_result(self, custom_id: str) -> MagicMock:
        r = MagicMock()
        r.custom_id = custom_id
        return r

    def test_all_received(self):
        context_map = {"id-1": {"_batch_filter_status": "included"}}
        results = [self._make_result("id-1")]
        assert BatchResultReconciler.find_missing_ids(context_map, results) == set()

    def test_some_missing(self):
        context_map = {
            "id-1": {"_batch_filter_status": "included"},
            "id-2": {"_batch_filter_status": "included"},
        }
        results = [self._make_result("id-1")]
        assert BatchResultReconciler.find_missing_ids(context_map, results) == {"id-2"}

    def test_empty_results(self):
        context_map = {"id-1": {"_batch_filter_status": "included"}}
        missing = BatchResultReconciler.find_missing_ids(context_map, [])
        assert "id-1" in missing

    def test_empty_context(self):
        results = [self._make_result("id-1")]
        assert BatchResultReconciler.find_missing_ids({}, results) == set()


# -- OnExhaustedPolicy coercion ----------------------------------------------


class TestOnExhaustedPolicyCoercion:
    """Verify __post_init__ coerces raw strings to OnExhaustedPolicy."""

    def test_string_coerced_to_enum(self):
        state = RecoveryState(phase="retry", on_exhausted="raise")
        assert state.on_exhausted is OnExhaustedPolicy.RAISE
        assert isinstance(state.on_exhausted, OnExhaustedPolicy)

    def test_default_is_return_last(self):
        state = RecoveryState(phase="retry")
        assert state.on_exhausted is OnExhaustedPolicy.RETURN_LAST

    def test_enum_value_unchanged(self):
        state = RecoveryState(phase="retry", on_exhausted=OnExhaustedPolicy.RAISE)
        assert state.on_exhausted is OnExhaustedPolicy.RAISE

    def test_json_roundtrip(self):
        """on_exhausted survives dict serialization + deserialization."""
        original = RecoveryState(phase="retry", on_exhausted=OnExhaustedPolicy.RAISE)
        data = original.to_dict()
        assert data["on_exhausted"] == "raise"
        restored = RecoveryState(**data)
        assert restored.on_exhausted is OnExhaustedPolicy.RAISE

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            RecoveryState(phase="retry", on_exhausted="invalid_policy")

    def test_str_equality_preserved(self):
        """Enum compares equal to raw string (str inheritance)."""
        assert OnExhaustedPolicy.RAISE == "raise"
        assert OnExhaustedPolicy.RETURN_LAST == "return_last"
