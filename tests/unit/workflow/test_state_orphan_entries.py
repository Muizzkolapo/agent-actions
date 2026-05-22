"""Tests for orphan status entry handling (P1-2 Bug B).

Verifies that is_workflow_complete, is_workflow_done, has_any_failed,
and get_summary iterate execution_order (current YAML actions) rather
than action_status (which may contain stale orphan entries from removed
actions).
"""

from agent_actions.workflow.managers.state import (
    ActionStatus,
    ActionStateManager,
)


def _make_state_manager(tmp_path, execution_order, extra_statuses=None):
    """Build a StateManager and inject orphan entries into action_status."""
    sm = ActionStateManager(
        status_file_path=tmp_path / "status.json",
        execution_order=execution_order,
    )
    if extra_statuses:
        for name, status in extra_statuses.items():
            sm.action_status[name] = {"status": status}
    return sm


class TestOrphanEntriesIgnored:
    """Orphan entries in action_status must not affect workflow-level queries."""

    def test_is_workflow_complete_ignores_orphan_failed(self, tmp_path):
        sm = _make_state_manager(
            tmp_path,
            execution_order=["action_a"],
            extra_statuses={"orphan_action": ActionStatus.FAILED},
        )
        sm.update_status("action_a", ActionStatus.COMPLETED)

        assert sm.is_workflow_complete() is True

    def test_is_workflow_complete_false_when_current_action_pending(self, tmp_path):
        sm = _make_state_manager(tmp_path, execution_order=["action_a", "action_b"])
        sm.update_status("action_a", ActionStatus.COMPLETED)
        # action_b is still PENDING

        assert sm.is_workflow_complete() is False

    def test_is_workflow_done_ignores_orphan_pending(self, tmp_path):
        sm = _make_state_manager(
            tmp_path,
            execution_order=["action_a"],
            extra_statuses={"orphan_action": ActionStatus.PENDING},
        )
        sm.update_status("action_a", ActionStatus.COMPLETED)

        assert sm.is_workflow_done() is True

    def test_is_workflow_done_false_when_current_running(self, tmp_path):
        sm = _make_state_manager(tmp_path, execution_order=["action_a"])
        sm.update_status("action_a", ActionStatus.RUNNING)

        assert sm.is_workflow_done() is False

    def test_has_any_failed_ignores_orphan_failed(self, tmp_path):
        sm = _make_state_manager(
            tmp_path,
            execution_order=["action_a"],
            extra_statuses={"orphan_action": ActionStatus.FAILED},
        )
        sm.update_status("action_a", ActionStatus.COMPLETED)

        assert sm.has_any_failed() is False

    def test_has_any_failed_true_when_current_action_failed(self, tmp_path):
        sm = _make_state_manager(tmp_path, execution_order=["action_a"])
        sm.update_status("action_a", ActionStatus.FAILED)

        assert sm.has_any_failed() is True

    def test_get_summary_excludes_orphans(self, tmp_path):
        sm = _make_state_manager(
            tmp_path,
            execution_order=["action_a", "action_b"],
            extra_statuses={"orphan_action": ActionStatus.FAILED},
        )
        sm.update_status("action_a", ActionStatus.COMPLETED)
        sm.update_status("action_b", ActionStatus.COMPLETED)

        summary = sm.get_summary()

        assert summary == {ActionStatus.COMPLETED: 2}
        assert ActionStatus.FAILED not in summary

    def test_get_summary_counts_only_current_actions(self, tmp_path):
        sm = _make_state_manager(
            tmp_path,
            execution_order=["action_a", "action_b"],
        )
        sm.update_status("action_a", ActionStatus.COMPLETED)
        # action_b stays PENDING

        summary = sm.get_summary()

        assert summary[ActionStatus.COMPLETED] == 1
        assert summary[ActionStatus.PENDING] == 1
        assert len(summary) == 2
