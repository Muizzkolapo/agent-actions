"""Tests for ActionExecutor event firing behavior."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.logging.events.batch_events import BatchCompleteEvent, BatchSubmittedEvent
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStatus


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
        # An empty registry, stated explicitly. Left as a bare MagicMock this
        # returns a Mock from load_metadata(), json.loads raises, and the read
        # is swallowed — so the test would assert through the error handler
        # instead of the no-registry path it means to describe.
        deps.action_runner.storage_backend.load_metadata.return_value = None
        # Pre/post snapshots needed by _count_records_for_action.
        deps.action_runner.storage_backend.get_storage_stats.return_value = {"nodes": {}}
        return deps

    @pytest.fixture
    def executor(self, mock_deps):
        """Create executor with mock dependencies."""
        return ActionExecutor(mock_deps)

    def test_batch_complete_fires_no_duplicate_event(self, executor, mock_deps):
        """finalize_batch_output already fired a populated one on this condition."""
        mock_deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor._handle_batch_check(
                action_name="test_agent",
                action_idx=0,
                action_config={},
                start_time=datetime.now(),
            )

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED

        fired = [c[0][0] for c in mock_fire.call_args_list]
        assert not [e for e in fired if isinstance(e, BatchCompleteEvent)]

    def test_batch_in_progress_claims_no_submission(self, executor, mock_deps):
        """A poll that found the job still running submitted nothing."""
        mock_deps.batch_manager.handle_batch_agent.return_value = (None, "in_progress")

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor._handle_batch_check(
                action_name="test_agent",
                action_idx=0,
                action_config={"model_vendor": "openai"},
                start_time=datetime.now(),
            )

        assert result.success is True
        assert result.status == ActionStatus.BATCH_SUBMITTED

        fired = [c[0][0] for c in mock_fire.call_args_list]
        assert not [e for e in fired if isinstance(e, BatchSubmittedEvent)]

    def test_batch_failed_fires_event(self, executor, mock_deps):
        """Should fire BatchCompleteEvent with failed count when batch fails."""
        mock_deps.batch_manager.handle_batch_agent.return_value = (None, "failed")

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor._handle_batch_check(
                action_name="test_agent",
                action_idx=0,
                action_config={},
                start_time=datetime.now(),
            )

        assert result.success is False
        assert result.status == ActionStatus.FAILED

        # The registry holds no record count, so there is no honest total to
        # report. ActionFailedEvent carries the failure; a BatchCompleteEvent
        # here could only invent one.
        fired = [c[0][0] for c in mock_fire.call_args_list]
        assert [e for e in fired if isinstance(e, BatchCompleteEvent)] == []
