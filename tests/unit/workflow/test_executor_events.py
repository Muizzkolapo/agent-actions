"""Tests for ActionExecutor event firing behavior."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.logging.events.batch_events import BatchCompleteEvent, BatchSubmittedEvent
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies


class TestHandleBatchCheckEventFiring:
    """Tests for _handle_batch_check event firing parity with async version."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock dependencies for executor."""
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock()
        deps.batch_manager = MagicMock()
        deps.action_runner = MagicMock()
        deps.action_runner.workflow_name = "test_workflow"
        deps.action_runner.get_action_folder.return_value = "/tmp/agent_io"
        deps.action_runner.storage_backend.get_failed_items.return_value = []
        deps.action_runner.storage_backend.has_disposition.return_value = False
        return deps

    @pytest.fixture
    def executor(self, mock_deps):
        """Create executor with mock dependencies."""
        return ActionExecutor(mock_deps)

    def test_batch_complete_fires_event(self, executor, mock_deps):
        """Should fire BatchCompleteEvent when batch status is completed."""
        mock_deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor._handle_batch_check(
                action_name="test_agent",
                action_idx=0,
                action_config={"batch_id": "batch_123"},
                start_time=datetime.now(),
            )

        assert result.success is True
        assert result.status == "completed"

        # Verify BatchCompleteEvent was fired
        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert isinstance(event, BatchCompleteEvent)
        assert event.action_name == "test_agent"
        assert event.batch_id == "batch_123"
        assert event.completed == 1
        assert event.failed == 0

    def test_batch_in_progress_fires_event(self, executor, mock_deps):
        """Should fire BatchSubmittedEvent when batch is still in progress."""
        mock_deps.batch_manager.handle_batch_agent.return_value = (None, "in_progress")

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor._handle_batch_check(
                action_name="test_agent",
                action_idx=0,
                action_config={"batch_id": "batch_456", "model_vendor": "openai"},
                start_time=datetime.now(),
            )

        assert result.success is True
        assert result.status == "batch_submitted"

        # Verify BatchSubmittedEvent was fired
        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert isinstance(event, BatchSubmittedEvent)
        assert event.action_name == "test_agent"
        assert event.batch_id == "batch_456"

    def test_batch_failed_fires_event(self, executor, mock_deps):
        """Should fire BatchCompleteEvent with failed count when batch fails."""
        mock_deps.batch_manager.handle_batch_agent.return_value = (None, "failed")

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor._handle_batch_check(
                action_name="test_agent",
                action_idx=0,
                action_config={"batch_id": "batch_789"},
                start_time=datetime.now(),
            )

        assert result.success is False
        assert result.status == "failed"

        # Verify BatchCompleteEvent was fired with failure
        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert isinstance(event, BatchCompleteEvent)
        assert event.action_name == "test_agent"
        assert event.completed == 0
        assert event.failed == 1
