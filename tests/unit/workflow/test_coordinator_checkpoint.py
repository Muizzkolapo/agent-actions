"""Tests for selective disposition clearing on RUNNING action reset.

When an action is interrupted mid-processing (status=RUNNING), checkpointed
SUCCESS dispositions must survive the reset so the DispositionGate can carry
them forward on resume.  Other retryable statuses (FAILED, SKIPPED, etc.)
still get a full bulk wipe because they have no SUCCESS dispositions to preserve.
"""

from unittest.mock import MagicMock

from agent_actions.storage.backend import (
    DISPOSITION_SUCCESS,
    RUNNING_CLEAR_DISPOSITIONS,
)
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


def _run_reset_logic(tmp_path, actions, statuses, mock_storage):
    """Reproduce _reset_retryable_actions using RUNNING_CLEAR_DISPOSITIONS."""
    mgr = ActionStateManager(tmp_path / "status.json", actions)
    for name, status in zip(actions, statuses, strict=True):
        mgr.update_status(name, status)

    running_actions = {
        name for name in mgr.execution_order if mgr.get_status(name) == ActionStatus.RUNNING
    }
    reset_actions = mgr.reset_retryable()

    for action_name in reset_actions:
        if action_name in running_actions:
            for disp in RUNNING_CLEAR_DISPOSITIONS:
                mock_storage.clear_disposition(action_name, disp)
        else:
            mock_storage.clear_disposition(action_name)
        mock_storage.clear_prompt_traces(action_name)

    return reset_actions, running_actions


class TestRunningActionPreservesSuccessDispositions:
    """RUNNING actions should only clear failure dispositions, not SUCCESS."""

    def test_running_clears_only_failure_dispositions(self, tmp_path):
        """A RUNNING action clears RUNNING_CLEAR_DISPOSITIONS but not SUCCESS."""
        mock_storage = MagicMock()
        reset_actions, running = _run_reset_logic(
            tmp_path, ["action_a"], [ActionStatus.RUNNING], mock_storage
        )

        assert reset_actions == ["action_a"]
        assert "action_a" in running

        assert mock_storage.clear_disposition.call_count == len(RUNNING_CLEAR_DISPOSITIONS)
        cleared_disps = {c.args[1] for c in mock_storage.clear_disposition.call_args_list}
        assert cleared_disps == RUNNING_CLEAR_DISPOSITIONS
        assert DISPOSITION_SUCCESS not in cleared_disps

    def test_failed_action_bulk_wipes_all_dispositions(self, tmp_path):
        """A FAILED action still bulk-wipes all dispositions."""
        mock_storage = MagicMock()
        _run_reset_logic(tmp_path, ["action_a"], [ActionStatus.FAILED], mock_storage)

        mock_storage.clear_disposition.assert_called_once_with("action_a")

    def test_mixed_statuses_apply_correct_clearing(self, tmp_path):
        """RUNNING gets selective clear, FAILED gets bulk clear, COMPLETED is untouched."""
        mock_storage = MagicMock()
        reset_actions, _ = _run_reset_logic(
            tmp_path,
            ["running_action", "failed_action", "done_action"],
            [ActionStatus.RUNNING, ActionStatus.FAILED, ActionStatus.COMPLETED],
            mock_storage,
        )

        assert len(reset_actions) == 2
        assert "done_action" not in reset_actions

        calls = mock_storage.clear_disposition.call_args_list
        running_calls = [c for c in calls if c.args[0] == "running_action"]
        failed_calls = [c for c in calls if c.args[0] == "failed_action"]

        assert len(running_calls) == len(RUNNING_CLEAR_DISPOSITIONS)
        assert len(failed_calls) == 1
        assert failed_calls[0].args == ("failed_action",)
