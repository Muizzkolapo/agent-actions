"""Tests for ActionStateManager.is_workflow_done() and updated get_pending_actions()."""

from agent_actions.workflow.managers.state import ActionStateManager


class TestIsWorkflowDone:
    """Tests for is_workflow_done()."""

    def test_true_when_all_completed(self, tmp_path):
        """is_workflow_done returns True when all actions are completed."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "completed")

        assert mgr.is_workflow_done() is True

    def test_true_when_mix_of_completed_and_failed(self, tmp_path):
        """is_workflow_done returns True when all actions are completed or failed."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "failed")
        mgr.update_status("c", "completed")

        assert mgr.is_workflow_done() is True

    def test_false_when_some_still_pending(self, tmp_path):
        """is_workflow_done returns False when some actions are still pending."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "failed")
        # c stays pending

        assert mgr.is_workflow_done() is False

    def test_false_when_some_still_running(self, tmp_path):
        """is_workflow_done returns False when some actions are still running."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "running")

        assert mgr.is_workflow_done() is False


class TestGetPendingActionsExcludesFailed:
    """Tests for get_pending_actions() excluding both completed AND failed."""

    def test_excludes_completed(self, tmp_path):
        """get_pending_actions excludes completed actions."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", "completed")

        pending = mgr.get_pending_actions(["a", "b", "c"])
        assert "a" not in pending
        assert "b" in pending
        assert "c" in pending

    def test_excludes_failed(self, tmp_path):
        """get_pending_actions excludes failed actions."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "failed")

        pending = mgr.get_pending_actions(["a", "b", "c"])
        assert "a" not in pending
        assert "b" not in pending
        assert "c" in pending

    def test_excludes_both_completed_and_failed(self, tmp_path):
        """get_pending_actions excludes both completed and failed."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c", "d"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "failed")
        mgr.update_status("c", "running")
        # d stays pending

        pending = mgr.get_pending_actions(["a", "b", "c", "d"])
        assert pending == ["c", "d"]

    def test_all_terminal_returns_empty(self, tmp_path):
        """When all are completed/failed, returns empty list."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "failed")

        pending = mgr.get_pending_actions(["a", "b"])
        assert pending == []
