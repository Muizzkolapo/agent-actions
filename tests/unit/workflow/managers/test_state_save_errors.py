"""Tests that status save and disposition clear failures propagate as exceptions."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


class TestSaveStatusErrorPropagation:
    """_save_status must raise on I/O failure, not swallow exceptions."""

    @pytest.mark.parametrize(
        ("error", "call"),
        [
            pytest.param(
                OSError("disk full"),
                lambda mgr: mgr.update_status("action_a", ActionStatus.COMPLETED),
                id="update_status_oserror",
            ),
            pytest.param(
                ValueError("not serializable"),
                lambda mgr: mgr._save_status(),
                id="save_status_valueerror",
            ),
            pytest.param(OSError("disk full"), lambda mgr: mgr.reset(), id="reset_oserror"),
        ],
    )
    def test_a_failed_status_write_propagates(self, tmp_path, error, call):
        mgr = ActionStateManager(tmp_path / "status.json", ["action_a"])

        with patch(
            "agent_actions.workflow.managers.state.atomic_json_write",
            side_effect=error,
        ):
            with pytest.raises(type(error), match=str(error)):
                call(mgr)

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
        action_runner.retried_records = frozenset()
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
