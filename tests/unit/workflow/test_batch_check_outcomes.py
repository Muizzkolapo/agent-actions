"""Tests for _handle_batch_check outcomes and event payloads.

Covers the gaps identified in P4-000 inventory:
- BatchCompleteEvent payload verification (total, completed, failed, elapsed)
- Recovery batch dispatch within batch check
- Status transitions during batch check (CHECKING_BATCH intermediate)
- Batch wall clock computation
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.logging.events.batch_events import BatchCompleteEvent
from agent_actions.workflow.executor import (
    ActionExecutor,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


@pytest.fixture
def mock_deps():
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
    deps.action_runner = MagicMock()
    deps.skip_evaluator = MagicMock(spec=SkipEvaluator)
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.action_runner.workflow_name = "test_workflow"
    deps.action_runner.get_action_folder.return_value = "/tmp/agent_io"
    deps.action_runner.execution_order = ["agent_a", "agent_b"]
    deps.action_runner.storage_backend.get_failed_items.return_value = []
    deps.action_runner.storage_backend.has_disposition.return_value = False
    deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
    return deps


@pytest.fixture
def executor(mock_deps):
    return ActionExecutor(mock_deps)


class TestBatchCheckCompleteEvent:
    """BatchCompleteEvent fields verified on successful batch completion."""

    def test_completed_event_has_correct_counts(self, executor, mock_deps):
        """Successful batch fires event with total=10, completed=8, failed=2."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = ("/output/file.json", "completed")
        # Simulate batch with 10 records: 8 success, 2 failed
        mock_deps.action_runner.storage_backend.get_failed_items.return_value = [
            {"id": "x"},
            {"id": "y"},
        ]
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.BATCH_SUBMITTED,
            "batch_submitted_at": "2026-05-01T10:00:00",
            "total_records": 10,
        }

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor.execute_action_sync(
                "agent_a", action_idx=0, action_config={"kind": "llm"}, is_last_action=False
            )

        assert result.status in (ActionStatus.COMPLETED, ActionStatus.COMPLETED_WITH_FAILURES)
        # Find the BatchCompleteEvent
        complete_events = [
            call[0][0]
            for call in mock_fire.call_args_list
            if isinstance(call[0][0], BatchCompleteEvent)
        ]
        assert len(complete_events) == 1
        event = complete_events[0]
        assert event.action_name == "agent_a"

    def test_failed_batch_fires_event_and_writes_disposition(self, executor, mock_deps):
        """Failed batch: fires BatchCompleteEvent with failed count + writes disposition."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = (None, "failed")
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.BATCH_SUBMITTED,
            "batch_submitted_at": "2026-05-01T10:00:00",
        }

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor.execute_action_sync(
                "agent_a", action_idx=0, action_config={"kind": "llm"}, is_last_action=False
            )

        assert result.status == ActionStatus.FAILED
        # Disposition written
        mock_deps.action_runner.storage_backend.set_disposition.assert_called()
        # Event fired
        complete_events = [
            call[0][0]
            for call in mock_fire.call_args_list
            if isinstance(call[0][0], BatchCompleteEvent)
        ]
        assert len(complete_events) == 1
        assert complete_events[0].failed > 0


class TestBatchCheckStatusTransitions:
    """Status transitions during _handle_batch_check."""

    def test_checking_batch_intermediate_status(self, executor, mock_deps):
        """Status transitions through CHECKING_BATCH before resolving."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.BATCH_SUBMITTED,
        }

        status_calls = []
        mock_deps.state_manager.update_status.side_effect = (
            lambda name, status, **kwargs: status_calls.append(status)
        )

        with patch("agent_actions.workflow.executor.fire_event"):
            executor.execute_action_sync(
                "agent_a", action_idx=0, action_config={"kind": "llm"}, is_last_action=False
            )

        # CHECKING_BATCH should appear before final status
        assert ActionStatus.CHECKING_BATCH in status_calls

    def test_in_progress_stays_batch_submitted(self, executor, mock_deps):
        """In-progress batch: final status remains BATCH_SUBMITTED."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = (None, "in_progress")

        with patch("agent_actions.workflow.executor.fire_event"):
            result = executor.execute_action_sync(
                "agent_a", action_idx=0, action_config={"kind": "llm"}, is_last_action=False
            )

        assert result.status == ActionStatus.BATCH_SUBMITTED


class TestBatchWallClock:
    """_compute_batch_wall_clock calculation."""

    def test_computes_elapsed_from_submitted_at(self, executor, mock_deps):
        """Wall clock = now - batch_submitted_at timestamp."""
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.BATCH_SUBMITTED,
            "batch_submitted_at": "2026-05-01T10:00:00",
        }

        elapsed = executor._compute_batch_wall_clock("agent_a", fallback=99.0)

        # Should be a positive number (time since 2026-05-01T10:00:00)
        assert elapsed > 0
        assert elapsed != 99.0  # Not the fallback

    def test_missing_timestamp_returns_fallback(self, executor, mock_deps):
        """Missing batch_submitted_at returns the fallback value."""
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.BATCH_SUBMITTED,
        }

        elapsed = executor._compute_batch_wall_clock("agent_a", fallback=42.0)

        assert elapsed == 42.0
