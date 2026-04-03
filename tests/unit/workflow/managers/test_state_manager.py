"""Tests for ActionStateManager state persistence and queries."""

import json

import pytest

from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


class TestStateManagerInitialization:
    """Tests for ActionStateManager initialization behavior."""

    def test_new_file_defaults_to_pending(self, tmp_path):
        """All agents should start as 'pending' when no status file exists."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["agent_a", "agent_b"])

        assert mgr.get_status("agent_a") == ActionStatus.PENDING
        assert mgr.get_status("agent_b") == ActionStatus.PENDING

    def test_loads_existing_status_file(self, tmp_path):
        """Should load previously persisted status."""
        status_file = tmp_path / "status.json"
        status_file.write_text(json.dumps({"agent_a": {"status": "completed"}}))

        mgr = ActionStateManager(status_file, ["agent_a"])
        assert mgr.get_status("agent_a") == ActionStatus.COMPLETED

    def test_corrupted_file_falls_back_to_defaults(self, tmp_path):
        """Should fall back to pending when status file is invalid JSON."""
        status_file = tmp_path / "status.json"
        status_file.write_text("NOT VALID JSON {{{")

        mgr = ActionStateManager(status_file, ["agent_a"])
        assert mgr.get_status("agent_a") == ActionStatus.PENDING


class TestUpdateStatus:
    """Tests for update_status persistence."""

    def test_persists_status_to_file(self, tmp_path):
        """Status update should be written to disk."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["agent_a"])

        mgr.update_status("agent_a", ActionStatus.COMPLETED)

        saved = json.loads(status_file.read_text())
        assert saved["agent_a"]["status"] == "completed"

    def test_persists_with_metadata(self, tmp_path):
        """Extra metadata kwargs should be saved alongside status."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["agent_a"])

        mgr.update_status("agent_a", ActionStatus.FAILED, error="something broke")

        saved = json.loads(status_file.read_text())
        assert saved["agent_a"]["error"] == "something broke"

    def test_overwrites_previous_status(self, tmp_path):
        """Subsequent updates should overwrite the previous status."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["agent_a"])

        mgr.update_status("agent_a", ActionStatus.RUNNING)
        mgr.update_status("agent_a", ActionStatus.COMPLETED)

        assert mgr.get_status("agent_a") == ActionStatus.COMPLETED


class TestStatusQueries:
    """Tests for individual agent status query methods."""

    @pytest.fixture
    def mgr(self, tmp_path):
        status_file = tmp_path / "status.json"
        m = ActionStateManager(status_file, ["a", "b", "c"])
        m.update_status("a", ActionStatus.COMPLETED)
        m.update_status("b", ActionStatus.BATCH_SUBMITTED)
        m.update_status("c", ActionStatus.FAILED)
        return m

    def test_get_status_returns_current(self, mgr):
        assert mgr.get_status("a") == ActionStatus.COMPLETED

    def test_get_status_unknown_agent_defaults_pending(self, mgr):
        assert mgr.get_status("nonexistent") == ActionStatus.PENDING

    def test_get_status_details_returns_full_dict(self, mgr):
        details = mgr.get_status_details("a")
        assert details["status"] == ActionStatus.COMPLETED

    def test_is_completed(self, mgr):
        assert mgr.is_completed("a") is True
        assert mgr.is_completed("b") is False

    def test_is_batch_submitted(self, mgr):
        assert mgr.is_batch_submitted("b") is True
        assert mgr.is_batch_submitted("a") is False

    def test_is_failed(self, mgr):
        assert mgr.is_failed("c") is True
        assert mgr.is_failed("a") is False

    def test_is_terminal(self, mgr):
        assert mgr.is_terminal("a") is True  # completed
        assert mgr.is_terminal("c") is True  # failed
        assert mgr.is_terminal("b") is False  # batch_submitted

    def test_is_in_progress(self, mgr):
        assert mgr.is_in_progress("b") is True  # batch_submitted
        assert mgr.is_in_progress("a") is False  # completed (terminal)

    def test_is_in_progress_pending_is_false(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["x"])
        assert mgr.is_in_progress("x") is False  # pending, not started


class TestAgentListQueries:
    """Tests for list-based agent queries."""

    @pytest.fixture
    def mgr(self, tmp_path):
        status_file = tmp_path / "status.json"
        m = ActionStateManager(status_file, ["a", "b", "c"])
        m.update_status("a", ActionStatus.COMPLETED)
        m.update_status("b", ActionStatus.BATCH_SUBMITTED)
        # c stays pending
        return m

    def test_get_pending_actions(self, mgr):
        pending = mgr.get_pending_actions(["a", "b", "c"])
        assert pending == ["b", "c"]

    def test_get_batch_submitted_actions(self, mgr):
        batch = mgr.get_batch_submitted_actions(["a", "b", "c"])
        assert batch == ["b"]

    def test_get_failed_actions(self, mgr):
        mgr.update_status("c", ActionStatus.FAILED)
        failed = mgr.get_failed_actions(["a", "b", "c"])
        assert failed == ["c"]


class TestWorkflowLevel:
    """Tests for workflow-level state methods."""

    def test_mark_running_as_failed_marks_running(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", ActionStatus.RUNNING)

        result = mgr.mark_running_as_failed()

        assert result == ["a"]
        assert mgr.get_status("a") == ActionStatus.FAILED

    def test_mark_running_as_failed_marks_checking_batch(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.CHECKING_BATCH)

        result = mgr.mark_running_as_failed()

        assert result == ["a"]
        assert mgr.get_status("a") == ActionStatus.FAILED

    def test_mark_running_as_failed_marks_all(self, tmp_path):
        """All running/checking_batch agents should be marked failed."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", ActionStatus.RUNNING)
        mgr.update_status("b", ActionStatus.RUNNING)
        mgr.update_status("c", ActionStatus.CHECKING_BATCH)

        result = mgr.mark_running_as_failed()

        assert set(result) == {"a", "b", "c"}
        assert mgr.get_status("a") == ActionStatus.FAILED
        assert mgr.get_status("b") == ActionStatus.FAILED
        assert mgr.get_status("c") == ActionStatus.FAILED

    def test_mark_running_as_failed_returns_empty_if_none_running(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.COMPLETED)

        assert mgr.mark_running_as_failed() == []

    def test_is_workflow_complete_true(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", ActionStatus.COMPLETED)
        mgr.update_status("b", ActionStatus.COMPLETED)

        assert mgr.is_workflow_complete() is True

    def test_is_workflow_complete_false(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", ActionStatus.COMPLETED)

        assert mgr.is_workflow_complete() is False

    def test_has_any_failed(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", ActionStatus.FAILED)

        assert mgr.has_any_failed() is True

    def test_has_any_failed_none(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.COMPLETED)

        assert mgr.has_any_failed() is False

    def test_get_summary(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", ActionStatus.COMPLETED)
        mgr.update_status("b", ActionStatus.COMPLETED)
        mgr.update_status("c", ActionStatus.FAILED)

        summary = mgr.get_summary()
        assert summary == {ActionStatus.COMPLETED: 2, ActionStatus.FAILED: 1}

    def test_is_workflow_complete_empty_agents(self, tmp_path):
        """Empty agent list: all() on empty iterable returns True — document this behavior."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, [])

        assert mgr.is_workflow_complete() is True

    def test_update_status_unknown_agent_creates_entry(self, tmp_path):
        """Updating status for an agent not in execution_order should create a new entry."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])

        mgr.update_status("unknown_agent", ActionStatus.RUNNING)

        assert mgr.get_status("unknown_agent") == ActionStatus.RUNNING
        saved = json.loads(status_file.read_text())
        assert "unknown_agent" in saved

    def test_round_trip_persistence(self, tmp_path):
        """Status persisted by one manager should be loadable by another."""
        status_file = tmp_path / "status.json"
        mgr1 = ActionStateManager(status_file, ["a", "b"])
        mgr1.update_status("a", ActionStatus.COMPLETED)
        mgr1.update_status("b", ActionStatus.FAILED, error="timeout")

        mgr2 = ActionStateManager(status_file, ["a", "b"])

        assert mgr2.get_status("a") == ActionStatus.COMPLETED
        assert mgr2.get_status("b") == ActionStatus.FAILED
        assert mgr2.get_status_details("b")["error"] == "timeout"


class TestResetRetryable:
    """Tests for reset_retryable() — re-run retry behavior."""

    def test_resets_failed_to_pending(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.FAILED)

        reset = mgr.reset_retryable()

        assert mgr.get_status("a") == ActionStatus.PENDING
        assert reset == ["a"]

    def test_resets_skipped_to_pending(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.SKIPPED)

        reset = mgr.reset_retryable()

        assert mgr.get_status("a") == ActionStatus.PENDING
        assert reset == ["a"]

    def test_resets_running_to_pending(self, tmp_path):
        """RUNNING from a prior crash should be retried."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.RUNNING)

        reset = mgr.reset_retryable()

        assert mgr.get_status("a") == ActionStatus.PENDING
        assert reset == ["a"]

    def test_preserves_completed(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.COMPLETED)

        reset = mgr.reset_retryable()

        assert mgr.get_status("a") == ActionStatus.COMPLETED
        assert reset == []

    def test_preserves_completed_with_failures(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.COMPLETED_WITH_FAILURES)

        reset = mgr.reset_retryable()

        assert mgr.get_status("a") == ActionStatus.COMPLETED_WITH_FAILURES
        assert reset == []

    def test_preserves_batch_submitted(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.BATCH_SUBMITTED)

        reset = mgr.reset_retryable()

        assert mgr.get_status("a") == ActionStatus.BATCH_SUBMITTED
        assert reset == []

    def test_mixed_statuses(self, tmp_path):
        """Only non-completed terminal + running actions should be reset."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c", "d", "e"])
        mgr.update_status("a", ActionStatus.COMPLETED)
        mgr.update_status("b", ActionStatus.FAILED)
        mgr.update_status("c", ActionStatus.SKIPPED)
        mgr.update_status("d", ActionStatus.BATCH_SUBMITTED)
        mgr.update_status("e", ActionStatus.RUNNING)

        reset = mgr.reset_retryable()

        assert mgr.get_status("a") == ActionStatus.COMPLETED
        assert mgr.get_status("b") == ActionStatus.PENDING
        assert mgr.get_status("c") == ActionStatus.PENDING
        assert mgr.get_status("d") == ActionStatus.BATCH_SUBMITTED
        assert mgr.get_status("e") == ActionStatus.PENDING
        assert set(reset) == {"b", "c", "e"}

    def test_persists_to_disk(self, tmp_path):
        """Reset should be persisted so a new manager instance sees PENDING."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", ActionStatus.FAILED)
        mgr.reset_retryable()

        mgr2 = ActionStateManager(status_file, ["a"])
        assert mgr2.get_status("a") == ActionStatus.PENDING

    def test_empty_returns_empty(self, tmp_path):
        """All-pending status file returns empty reset list."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])

        reset = mgr.reset_retryable()

        assert reset == []
