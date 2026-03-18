"""Tests for ActionStateManager state persistence and queries."""

import json

import pytest

from agent_actions.workflow.managers.state import ActionStateManager


class TestStateManagerInitialization:
    """Tests for ActionStateManager initialization behavior."""

    def test_new_file_defaults_to_pending(self, tmp_path):
        """All agents should start as 'pending' when no status file exists."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["agent_a", "agent_b"])

        assert mgr.get_status("agent_a") == "pending"
        assert mgr.get_status("agent_b") == "pending"

    def test_loads_existing_status_file(self, tmp_path):
        """Should load previously persisted status."""
        status_file = tmp_path / "status.json"
        status_file.write_text(json.dumps({"agent_a": {"status": "completed"}}))

        mgr = ActionStateManager(status_file, ["agent_a"])
        assert mgr.get_status("agent_a") == "completed"

    def test_corrupted_file_falls_back_to_defaults(self, tmp_path):
        """Should fall back to pending when status file is invalid JSON."""
        status_file = tmp_path / "status.json"
        status_file.write_text("NOT VALID JSON {{{")

        mgr = ActionStateManager(status_file, ["agent_a"])
        assert mgr.get_status("agent_a") == "pending"


class TestUpdateStatus:
    """Tests for update_status persistence."""

    def test_persists_status_to_file(self, tmp_path):
        """Status update should be written to disk."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["agent_a"])

        mgr.update_status("agent_a", "completed")

        saved = json.loads(status_file.read_text())
        assert saved["agent_a"]["status"] == "completed"

    def test_persists_with_metadata(self, tmp_path):
        """Extra metadata kwargs should be saved alongside status."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["agent_a"])

        mgr.update_status("agent_a", "failed", error="something broke")

        saved = json.loads(status_file.read_text())
        assert saved["agent_a"]["error"] == "something broke"

    def test_overwrites_previous_status(self, tmp_path):
        """Subsequent updates should overwrite the previous status."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["agent_a"])

        mgr.update_status("agent_a", "running")
        mgr.update_status("agent_a", "completed")

        assert mgr.get_status("agent_a") == "completed"


class TestStatusQueries:
    """Tests for individual agent status query methods."""

    @pytest.fixture
    def mgr(self, tmp_path):
        status_file = tmp_path / "status.json"
        m = ActionStateManager(status_file, ["a", "b", "c"])
        m.update_status("a", "completed")
        m.update_status("b", "batch_submitted")
        m.update_status("c", "failed")
        return m

    def test_get_status_returns_current(self, mgr):
        assert mgr.get_status("a") == "completed"

    def test_get_status_unknown_agent_defaults_pending(self, mgr):
        assert mgr.get_status("nonexistent") == "pending"

    def test_get_status_details_returns_full_dict(self, mgr):
        details = mgr.get_status_details("a")
        assert details["status"] == "completed"

    def test_is_completed(self, mgr):
        assert mgr.is_completed("a") is True
        assert mgr.is_completed("b") is False

    def test_is_batch_submitted(self, mgr):
        assert mgr.is_batch_submitted("b") is True
        assert mgr.is_batch_submitted("a") is False

    def test_is_failed(self, mgr):
        assert mgr.is_failed("c") is True
        assert mgr.is_failed("a") is False


class TestAgentListQueries:
    """Tests for list-based agent queries."""

    @pytest.fixture
    def mgr(self, tmp_path):
        status_file = tmp_path / "status.json"
        m = ActionStateManager(status_file, ["a", "b", "c"])
        m.update_status("a", "completed")
        m.update_status("b", "batch_submitted")
        # c stays pending
        return m

    def test_get_pending_actions(self, mgr):
        pending = mgr.get_pending_actions(["a", "b", "c"])
        assert pending == ["b", "c"]

    def test_get_batch_submitted_actions(self, mgr):
        batch = mgr.get_batch_submitted_actions(["a", "b", "c"])
        assert batch == ["b"]

    def test_get_failed_actions(self, mgr):
        mgr.update_status("c", "failed")
        failed = mgr.get_failed_actions(["a", "b", "c"])
        assert failed == ["c"]


class TestWorkflowLevel:
    """Tests for workflow-level state methods."""

    def test_mark_running_as_failed_marks_running(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", "running")

        result = mgr.mark_running_as_failed()

        assert result == ["a"]
        assert mgr.get_status("a") == "failed"

    def test_mark_running_as_failed_marks_checking_batch(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", "checking_batch")

        result = mgr.mark_running_as_failed()

        assert result == ["a"]
        assert mgr.get_status("a") == "failed"

    def test_mark_running_as_failed_marks_all(self, tmp_path):
        """All running/checking_batch agents should be marked failed."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", "running")
        mgr.update_status("b", "running")
        mgr.update_status("c", "checking_batch")

        result = mgr.mark_running_as_failed()

        assert set(result) == {"a", "b", "c"}
        assert mgr.get_status("a") == "failed"
        assert mgr.get_status("b") == "failed"
        assert mgr.get_status("c") == "failed"

    def test_mark_running_as_failed_returns_empty_if_none_running(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", "completed")

        assert mgr.mark_running_as_failed() == []

    def test_is_workflow_complete_true(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "completed")

        assert mgr.is_workflow_complete() is True

    def test_is_workflow_complete_false(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", "completed")

        assert mgr.is_workflow_complete() is False

    def test_has_any_failed(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b"])
        mgr.update_status("a", "failed")

        assert mgr.has_any_failed() is True

    def test_has_any_failed_none(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])
        mgr.update_status("a", "completed")

        assert mgr.has_any_failed() is False

    def test_get_summary(self, tmp_path):
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a", "b", "c"])
        mgr.update_status("a", "completed")
        mgr.update_status("b", "completed")
        mgr.update_status("c", "failed")

        summary = mgr.get_summary()
        assert summary == {"completed": 2, "failed": 1}

    def test_is_workflow_complete_empty_agents(self, tmp_path):
        """Empty agent list: all() on empty iterable returns True — document this behavior."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, [])

        assert mgr.is_workflow_complete() is True

    def test_update_status_unknown_agent_creates_entry(self, tmp_path):
        """Updating status for an agent not in execution_order should create a new entry."""
        status_file = tmp_path / "status.json"
        mgr = ActionStateManager(status_file, ["a"])

        mgr.update_status("unknown_agent", "running")

        assert mgr.get_status("unknown_agent") == "running"
        saved = json.loads(status_file.read_text())
        assert "unknown_agent" in saved

    def test_round_trip_persistence(self, tmp_path):
        """Status persisted by one manager should be loadable by another."""
        status_file = tmp_path / "status.json"
        mgr1 = ActionStateManager(status_file, ["a", "b"])
        mgr1.update_status("a", "completed")
        mgr1.update_status("b", "failed", error="timeout")

        mgr2 = ActionStateManager(status_file, ["a", "b"])

        assert mgr2.get_status("a") == "completed"
        assert mgr2.get_status("b") == "failed"
        assert mgr2.get_status_details("b")["error"] == "timeout"
