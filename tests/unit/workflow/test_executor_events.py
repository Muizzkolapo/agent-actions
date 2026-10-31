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
        deps.action_runner.staged_input_fingerprint.return_value = None
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

    @pytest.mark.parametrize(
        ("handle_result", "action_config", "success", "status", "forbidden_event"),
        [
            # finalize_batch_output already fired a populated one on this condition.
            pytest.param(
                ("/output", "completed"),
                {},
                True,
                ActionStatus.COMPLETED,
                BatchCompleteEvent,
                id="completed_fires_no_duplicate_complete",
            ),
            # A poll that found the job still running submitted nothing.
            pytest.param(
                (None, "in_progress"),
                {"model_vendor": "openai"},
                True,
                ActionStatus.BATCH_SUBMITTED,
                BatchSubmittedEvent,
                id="in_progress_claims_no_submission",
            ),
            # The registry holds no record count, so a BatchCompleteEvent could only
            # invent a total; ActionFailedEvent carries the failure.
            pytest.param(
                (None, "failed"),
                {},
                False,
                ActionStatus.FAILED,
                BatchCompleteEvent,
                id="failed_fires_no_complete",
            ),
        ],
    )
    def test_batch_check_resolves_without_a_spurious_batch_event(
        self, executor, mock_deps, handle_result, action_config, success, status, forbidden_event
    ):
        mock_deps.batch_manager.handle_batch_agent.return_value = handle_result

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor._handle_batch_check(
                action_name="test_agent",
                action_idx=0,
                action_config=action_config,
                start_time=datetime.now(),
            )

        assert result.success is success
        assert result.status == status

        fired = [c[0][0] for c in mock_fire.call_args_list]
        assert [e for e in fired if isinstance(e, forbidden_event)] == []
