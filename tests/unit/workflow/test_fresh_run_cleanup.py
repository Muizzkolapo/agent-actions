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


class TestFreshRunClearsBatchState:
    """Batch state must be cleared via storage backend."""

    def test_clear_batch_state_called_per_action(self, tmp_path: Path):
        stub = _make_coordinator_stub(tmp_path, ["action1"])
        stub._clear_for_fresh_run()
        stub.storage_backend.clear_batch_state.assert_any_call("action1")

    def test_no_batch_dir_no_error(self, tmp_path: Path):
        stub = _make_coordinator_stub(tmp_path, ["action_no_batch"])
        stub._clear_for_fresh_run()

    def test_multiple_actions_batch_cleanup(self, tmp_path: Path):
        """Batch state cleared for each action in execution_order."""
        stub = _make_coordinator_stub(tmp_path, ["action_a", "action_b"])

        stub = _make_coordinator_stub(tmp_path, ["action_a", "action_b"])
        stub._clear_for_fresh_run()

        stub.storage_backend.clear_batch_state.assert_any_call("action_a")
        stub.storage_backend.clear_batch_state.assert_any_call("action_b")


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
        logs_dir = tmp_path / "agent_io" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "events.json").write_text("[]")
        (logs_dir / "errors.json").write_text("[]")

        stub = _make_coordinator_stub(tmp_path, ["a1"])
        stub._clear_for_fresh_run()

        assert not (logs_dir / "events.json").exists()
        assert not (logs_dir / "errors.json").exists()
