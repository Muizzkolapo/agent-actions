"""Tests for _clear_for_fresh_run completeness.

Verifies that --fresh clears source_data, batch recovery state files,
batch registry files, and batch carry-forward files in addition to
the existing target_data/disposition/prompt_trace cleanup.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock


def _make_coordinator_stub(
    tmp_path: Path,
    execution_order: list[str],
):
    """Build a minimal AgentWorkflow-like object with just enough to call _clear_for_fresh_run."""
    from agent_actions.workflow.coordinator import AgentWorkflow

    storage = MagicMock()
    storage.delete_target = MagicMock()
    storage.clear_disposition = MagicMock()
    storage.clear_prompt_traces = MagicMock()
    storage.clear_source_data = MagicMock()

    config = MagicMock()
    config.resolve_project_root.return_value = tmp_path

    state_manager = MagicMock()

    services = MagicMock()
    services.core.state_manager = state_manager

    runtime = MagicMock()

    # Build a stub that has the right attributes without calling __init__
    stub = object.__new__(AgentWorkflow)
    stub.storage_backend = storage
    stub.config = config
    stub.services = services
    stub.runtime = runtime
    stub.metadata = MagicMock()
    stub.metadata.execution_order = execution_order

    return stub


class TestFreshRunClearsSourceData:
    """source_data table must be cleared by --fresh."""

    def test_clear_source_data_called(self, tmp_path: Path):
        stub = _make_coordinator_stub(tmp_path, ["action1"])
        stub._clear_for_fresh_run()

        stub.storage_backend.clear_source_data.assert_called_once()

    def test_clear_source_data_after_per_action_cleanup(self, tmp_path: Path):
        """clear_source_data is workflow-level, called after the per-action loop."""
        call_order: list[str] = []

        stub = _make_coordinator_stub(tmp_path, ["a1", "a2"])
        stub.storage_backend.delete_target.side_effect = lambda name: call_order.append(
            f"delete_target:{name}"
        )
        stub.storage_backend.clear_source_data.side_effect = lambda: call_order.append(
            "clear_source_data"
        )

        stub._clear_for_fresh_run()

        # clear_source_data must come after all per-action delete_target calls
        source_idx = call_order.index("clear_source_data")
        for action in ["a1", "a2"]:
            assert call_order.index(f"delete_target:{action}") < source_idx

    def test_clear_source_data_failure_does_not_abort(self, tmp_path: Path):
        """If clear_source_data raises, the rest of cleanup still runs."""
        stub = _make_coordinator_stub(tmp_path, ["action1"])
        stub.storage_backend.clear_source_data.side_effect = RuntimeError("db locked")

        # Should not raise
        stub._clear_for_fresh_run()

        # state_manager.reset() should still be called
        stub.services.core.state_manager.reset.assert_called_once()


class TestFreshRunClearsBatchFiles:
    """Batch recovery state, registry, and carry-forward files must be deleted."""

    def _create_batch_files(self, tmp_path: Path, action_name: str) -> Path:
        batch_dir = tmp_path / "agent_io" / "target" / action_name / "batch"
        batch_dir.mkdir(parents=True)

        (batch_dir / ".recovery_state_abc123.json").write_text(json.dumps({"attempt": 3}))
        (batch_dir / ".recovery_state_def456.json").write_text(json.dumps({"attempt": 1}))
        (batch_dir / ".batch_registry.json").write_text(json.dumps({"batch_id": "expired_123"}))
        (batch_dir / ".batch_carry_forward.json").write_text(json.dumps({}))

        # Also create a normal output file that should NOT be deleted
        (batch_dir / "output_results.json").write_text(json.dumps([{"data": "keep"}]))

        return batch_dir

    def test_recovery_state_files_deleted(self, tmp_path: Path):
        batch_dir = self._create_batch_files(tmp_path, "action1")
        stub = _make_coordinator_stub(tmp_path, ["action1"])

        stub._clear_for_fresh_run()

        assert list(batch_dir.glob(".recovery_state_*.json")) == []

    def test_batch_registry_deleted(self, tmp_path: Path):
        batch_dir = self._create_batch_files(tmp_path, "action1")
        stub = _make_coordinator_stub(tmp_path, ["action1"])

        stub._clear_for_fresh_run()

        assert not (batch_dir / ".batch_registry.json").exists()

    def test_batch_carry_forward_deleted(self, tmp_path: Path):
        batch_dir = self._create_batch_files(tmp_path, "action1")
        stub = _make_coordinator_stub(tmp_path, ["action1"])

        stub._clear_for_fresh_run()

        assert not (batch_dir / ".batch_carry_forward.json").exists()

    def test_normal_output_files_preserved(self, tmp_path: Path):
        batch_dir = self._create_batch_files(tmp_path, "action1")
        stub = _make_coordinator_stub(tmp_path, ["action1"])

        stub._clear_for_fresh_run()

        assert (batch_dir / "output_results.json").exists()

    def test_no_batch_dir_no_error(self, tmp_path: Path):
        """If the batch directory doesn't exist, no error is raised."""
        stub = _make_coordinator_stub(tmp_path, ["action_no_batch"])

        # Should not raise
        stub._clear_for_fresh_run()

    def test_multiple_actions_batch_cleanup(self, tmp_path: Path):
        """Batch files cleaned for each action in execution_order."""
        batch_dir_a = self._create_batch_files(tmp_path, "action_a")
        batch_dir_b = self._create_batch_files(tmp_path, "action_b")

        stub = _make_coordinator_stub(tmp_path, ["action_a", "action_b"])
        stub._clear_for_fresh_run()

        assert list(batch_dir_a.glob(".recovery_state_*.json")) == []
        assert not (batch_dir_a / ".batch_registry.json").exists()
        assert list(batch_dir_b.glob(".recovery_state_*.json")) == []
        assert not (batch_dir_b / ".batch_registry.json").exists()


class TestFreshRunExistingBehavior:
    """Existing cleanup behavior must be preserved."""

    def test_delete_target_called_per_action(self, tmp_path: Path):
        stub = _make_coordinator_stub(tmp_path, ["a1", "a2"])
        stub._clear_for_fresh_run()

        assert stub.storage_backend.delete_target.call_count == 2
        stub.storage_backend.delete_target.assert_any_call("a1")
        stub.storage_backend.delete_target.assert_any_call("a2")

    def test_clear_disposition_called_per_action(self, tmp_path: Path):
        stub = _make_coordinator_stub(tmp_path, ["a1", "a2"])
        stub._clear_for_fresh_run()

        assert stub.storage_backend.clear_disposition.call_count == 2

    def test_clear_prompt_traces_called_per_action(self, tmp_path: Path):
        stub = _make_coordinator_stub(tmp_path, ["a1", "a2"])
        stub._clear_for_fresh_run()

        assert stub.storage_backend.clear_prompt_traces.call_count == 2

    def test_state_manager_reset_called(self, tmp_path: Path):
        stub = _make_coordinator_stub(tmp_path, ["a1"])
        stub._clear_for_fresh_run()

        stub.services.core.state_manager.reset.assert_called_once()

    def test_event_log_files_cleared(self, tmp_path: Path):
        target_dir = tmp_path / "agent_io" / "target"
        target_dir.mkdir(parents=True)
        (target_dir / "events.json").write_text("[]")
        (target_dir / "errors.json").write_text("[]")

        stub = _make_coordinator_stub(tmp_path, ["a1"])
        stub._clear_for_fresh_run()

        assert not (target_dir / "events.json").exists()
        assert not (target_dir / "errors.json").exists()
