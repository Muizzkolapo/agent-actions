"""Tests for ActionStateManager extension methods (is_workflow_done, get_pending_actions, get_skipped_actions, etc.)."""

import pytest

from agent_actions.workflow.managers.state import ActionStateManager


def _manager(tmp_path, statuses: dict[str, str]) -> ActionStateManager:
    mgr = ActionStateManager(tmp_path / "status.json", list(statuses))
    for action, status in statuses.items():
        if status != "pending":
            mgr.update_status(action, status)
    return mgr


class TestIsWorkflowDone:
    @pytest.mark.parametrize(
        ("statuses", "done"),
        [
            pytest.param({"a": "completed", "b": "completed"}, True, id="all_completed"),
            pytest.param(
                {"a": "completed", "b": "failed", "c": "completed"}, True, id="completed_and_failed"
            ),
            pytest.param(
                {"a": "completed", "b": "failed", "c": "skipped"},
                True,
                id="completed_failed_and_skipped",
            ),
            pytest.param(
                {"a": "completed_with_failures", "b": "failed"}, True, id="partial_and_failed"
            ),
            pytest.param(
                {"a": "completed", "b": "failed", "c": "pending"}, False, id="some_still_pending"
            ),
            pytest.param({"a": "completed", "b": "running"}, False, id="some_still_running"),
        ],
    )
    def test_is_workflow_done(self, tmp_path, statuses, done):
        assert _manager(tmp_path, statuses).is_workflow_done() is done


class TestGetPendingActions:
    """get_pending_actions() excludes every terminal status."""

    @pytest.mark.parametrize(
        ("statuses", "pending"),
        [
            pytest.param(
                {"a": "completed", "b": "pending", "c": "pending"}, ["b", "c"], id="completed"
            ),
            pytest.param({"a": "completed", "b": "failed", "c": "pending"}, ["c"], id="failed"),
            pytest.param(
                {"a": "completed", "b": "failed", "c": "running", "d": "pending"},
                ["c", "d"],
                id="completed_and_failed_keep_running",
            ),
            pytest.param({"a": "completed", "b": "skipped", "c": "pending"}, ["c"], id="skipped"),
            pytest.param(
                {"a": "completed_with_failures", "b": "pending"},
                ["b"],
                id="completed_with_failures",
            ),
            pytest.param({"a": "completed", "b": "failed"}, [], id="all_terminal"),
        ],
    )
    def test_excludes_terminal_actions(self, tmp_path, statuses, pending):
        assert _manager(tmp_path, statuses).get_pending_actions(list(statuses)) == pending


class TestIsSkipped:
    """Tests for is_skipped()."""

    def test_is_skipped_true(self, tmp_path):
        """is_skipped returns True for skipped actions."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", "skipped")

        assert mgr.is_skipped("a") is True

    def test_is_skipped_false_for_other_statuses(self, tmp_path):
        """is_skipped returns False for non-skipped actions."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "failed")

        assert mgr.is_skipped("a") is False
        assert mgr.is_skipped("b") is False
        assert mgr.is_skipped("c") is False


class TestWorkflowDoneWithSkipped:
    """Tests for is_workflow_done() with skipped status."""

    def test_summary_with_skipped(self, tmp_path):
        """get_summary correctly counts skipped actions."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "skipped")
        mgr.update_status("c", "failed")

        summary = mgr.get_summary()
        assert summary == {"completed": 1, "skipped": 1, "failed": 1}


class TestCompletedWithFailures:
    """Tests for completed_with_failures status."""

    def test_is_completed_with_failures(self, tmp_path):
        mgr = ActionStateManager(tmp_path / "s.json", ["a"])
        mgr.update_status("a", "completed_with_failures")
        assert mgr.is_completed_with_failures("a") is True
        assert mgr.is_completed("a") is True  # is_completed includes partial

    def test_is_completed_with_failures_false(self, tmp_path):
        mgr = ActionStateManager(tmp_path / "s.json", ["a", "b"])
        mgr.update_status("a", "completed")
        assert mgr.is_completed_with_failures("a") is False
        assert mgr.is_completed_with_failures("b") is False

    def test_is_workflow_complete_with_partial(self, tmp_path):
        mgr = ActionStateManager(tmp_path / "s.json", ["a", "b"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "completed_with_failures")
        assert mgr.is_workflow_complete() is True

    def test_summary_with_partial(self, tmp_path):
        mgr = ActionStateManager(tmp_path / "s.json", ["a", "b", "c"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "completed_with_failures")
        mgr.update_status("c", "failed")
        summary = mgr.get_summary()
        assert summary == {"completed": 1, "completed_with_failures": 1, "failed": 1}


class TestGetSkippedActions:
    """Tests for get_skipped_actions()."""

    def test_returns_skipped_actions(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "skipped")
        mgr.update_status("c", "failed")

        assert mgr.get_skipped_actions(["a", "b", "c"]) == ["b"]

    def test_returns_empty_when_none_skipped(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "failed")

        assert mgr.get_skipped_actions(["a", "b"]) == []
