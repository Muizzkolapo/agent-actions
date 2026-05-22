"""Tests that status save and disposition clear failures propagate as exceptions."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


class TestSaveStatusErrorPropagation:
    """_save_status must raise on I/O failure, not swallow exceptions."""

    def test_oserror_propagates_through_update_status(self, tmp_path):
        """OSError from atomic_json_write must propagate through update_status."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["action_a"])

        with patch(
            "agent_actions.workflow.managers.state.atomic_json_write",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(OSError, match="disk full"):
                mgr.update_status("action_a", ActionStatus.COMPLETED)

    def test_value_error_propagates_through_save_status(self, tmp_path):
        """ValueError from atomic_json_write (serialization bug) must propagate."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["action_a"])

        with patch(
            "agent_actions.workflow.managers.state.atomic_json_write",
            side_effect=ValueError("not serializable"),
        ):
            with pytest.raises(ValueError, match="not serializable"):
                mgr._save_status()

    def test_mkdir_failure_propagates(self, tmp_path):
        """If the status directory can't be created, the error must propagate."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["action_a"])

        with patch.object(
            type(mgr.status_file.parent),
            "mkdir",
            side_effect=OSError("permission denied"),
        ):
            with pytest.raises(OSError, match="permission denied"):
                mgr._save_status()

    def test_reset_save_failure_propagates(self, tmp_path):
        """If save fails during reset(), the error must propagate."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["action_a"])

        with patch(
            "agent_actions.workflow.managers.state.atomic_json_write",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(OSError, match="disk full"):
                mgr.reset()


class TestClearDispositionErrorPropagation:
    """clear_disposition failure in _maybe_invalidate must propagate."""

    def test_clear_disposition_error_propagates(self, tmp_path):
        """sqlite3.OperationalError from clear_disposition must propagate."""
        status_file = tmp_path / "status.json"
        state_mgr = ActionStateManager(status_file, ["action_a"])
        state_mgr.update_status("action_a", ActionStatus.COMPLETED, record_limit=10)

        storage = MagicMock()
        storage.clear_disposition.side_effect = sqlite3.OperationalError("database is locked")

        action_runner = MagicMock()
        action_runner.storage_backend = storage
        deps = ExecutorDependencies(
            action_runner=action_runner,
            state_manager=state_mgr,
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=MagicMock(),
        )
        executor = ActionExecutor(deps)

        action_config = {"record_limit": 20}  # changed from 10 to trigger invalidation

        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            executor._maybe_invalidate_completed_status(
                "action_a", action_config, ActionStatus.COMPLETED
            )
