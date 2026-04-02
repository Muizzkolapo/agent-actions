"""Tests for WorkflowEventLogger event firing methods."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.logging.events import (
    ActionCompleteEvent,
    ActionFailedEvent,
    ActionSkipEvent,
    ActionStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    WorkflowStartEvent,
)
from agent_actions.workflow.execution_events import WorkflowEventLogger
from agent_actions.workflow.managers.state import ActionStatus
from agent_actions.workflow.models import (
    ActionLogParams,
    CoreServices,
    SupportServices,
    WorkflowPaths,
    WorkflowRuntimeConfig,
    WorkflowServices,
)

FIRE_EVENT_PATH = "agent_actions.workflow.execution_events.fire_event"
GET_MANAGER_PATH = "agent_actions.workflow.execution_events.get_manager"
GET_ERROR_DETAIL_PATH = "agent_actions.workflow.execution_events.get_error_detail"


@pytest.fixture
def mock_services():
    """Build WorkflowServices with mock core/support."""
    core = MagicMock(spec=CoreServices)
    core.state_manager = MagicMock()
    support = MagicMock(spec=SupportServices)
    support.manifest_manager = MagicMock()
    return WorkflowServices(core=core, support=support)


@pytest.fixture
def mock_config():
    paths = MagicMock(spec=WorkflowPaths)
    cfg = MagicMock(spec=WorkflowRuntimeConfig)
    cfg.paths = paths
    cfg.run_upstream = False
    cfg.run_downstream = False
    return cfg


@pytest.fixture
def event_logger(mock_services, mock_config):
    return WorkflowEventLogger(
        agent_name="test_workflow",
        execution_order=["agent_a", "agent_b"],
        config=mock_config,
        services=mock_services,
    )


# ── log_workflow_start ─────────────────────────────────────────────────


class TestLogWorkflowStart:
    def test_sequential_mode(self, event_logger, mock_config):
        mgr = MagicMock()
        mgr.get_context.return_value = "abcd1234"
        with patch(FIRE_EVENT_PATH) as mock_fire, patch(GET_MANAGER_PATH, return_value=mgr):
            event_logger.log_workflow_start(datetime.now(), is_async=False)

        event = mock_fire.call_args[0][0]
        assert isinstance(event, WorkflowStartEvent)
        assert event.workflow_name == "test_workflow"
        assert event.execution_mode == "sequential"
        assert event.action_count == 2
        assert event.run_upstream == mock_config.run_upstream
        assert event.run_downstream == mock_config.run_downstream

    def test_async_mode(self, event_logger):
        mgr = MagicMock()
        mgr.get_context.return_value = "abcd1234"
        with patch(FIRE_EVENT_PATH) as mock_fire, patch(GET_MANAGER_PATH, return_value=mgr):
            event_logger.log_workflow_start(datetime.now(), is_async=True)

        event = mock_fire.call_args[0][0]
        assert isinstance(event, WorkflowStartEvent)
        assert event.execution_mode == "async"


# ── fire_action_start ───────────────────────────────────────────────────


class TestFireAgentStart:
    def test_fires_agent_start_event(self, event_logger):
        with patch(FIRE_EVENT_PATH) as mock_fire:
            event_logger.fire_action_start(0, "agent_a", 2, {"type": "llm"})

        event = mock_fire.call_args[0][0]
        assert isinstance(event, ActionStartEvent)
        assert event.action_name == "agent_a"
        assert event.action_index == 0
        assert event.total_actions == 2
        assert event.action_type == "llm"


# ── log_action_skip ─────────────────────────────────────────────────────


class TestLogAgentSkip:
    def test_fires_agent_skip_event(self, event_logger):
        """log_action_skip should fire ActionSkipEvent with 'already completed' reason."""
        with patch(FIRE_EVENT_PATH) as mock_fire:
            event_logger.log_action_skip(1, "agent_b", 3)

        event = mock_fire.call_args[0][0]
        assert isinstance(event, ActionSkipEvent)
        assert event.action_name == "agent_b"
        assert event.action_index == 1
        assert event.total_actions == 3
        assert event.skip_reason == "already completed"


# ── log_action_result ───────────────────────────────────────────────────


class TestLogAgentResult:
    def _make_result(self, success=True, status=ActionStatus.COMPLETED, error=None, tokens=None):
        r = MagicMock()
        r.success = success
        r.status = status
        r.error = error
        r.tokens = tokens
        r.output_folder = "/output"
        return r

    def test_completed_fires_agent_complete(self, event_logger):
        result = self._make_result(tokens={"total_tokens": 100})
        params = ActionLogParams(
            idx=0,
            action_name="agent_a",
            total_actions=2,
            result=result,
            end_time=datetime.now(),
            duration=1.5,
        )

        with patch(FIRE_EVENT_PATH) as mock_fire:
            event_logger.log_action_result(params)

        event = mock_fire.call_args[0][0]
        assert isinstance(event, ActionCompleteEvent)
        assert event.action_name == "agent_a"
        assert event.action_index == 0
        assert event.total_actions == 2
        assert event.execution_time == 1.5
        assert event.output_path == "/output"
        assert event.tokens == {"total_tokens": 100}

    def test_failed_fires_agent_failed(self, event_logger):
        error = RuntimeError("agent crashed")
        result = self._make_result(success=False, status=ActionStatus.FAILED, error=error)
        params = ActionLogParams(
            idx=0,
            action_name="agent_a",
            total_actions=2,
            result=result,
            end_time=datetime.now(),
            duration=0.5,
        )

        with (
            patch(FIRE_EVENT_PATH) as mock_fire,
            patch(GET_ERROR_DETAIL_PATH, return_value="detail"),
        ):
            event_logger.log_action_result(params)

        event = mock_fire.call_args[0][0]
        assert isinstance(event, ActionFailedEvent)
        assert event.action_name == "agent_a"
        assert event.error_type == "RuntimeError"
        assert event.error_message == "agent crashed"
        assert event.error_detail == "detail"
        assert event.execution_time == 0.5

    def test_batch_submitted_no_extra_event(self, event_logger):
        """batch_submitted results should not fire additional events."""
        result = self._make_result(success=True, status=ActionStatus.BATCH_SUBMITTED)
        params = ActionLogParams(
            idx=0,
            action_name="agent_a",
            total_actions=2,
            result=result,
            end_time=datetime.now(),
            duration=0.1,
        )

        with patch(FIRE_EVENT_PATH) as mock_fire:
            event_logger.log_action_result(params)

        mock_fire.assert_not_called()


# ── finalize_workflow ──────────────────────────────────────────────────


class TestFinalizeWorkflow:
    def test_fires_workflow_complete_event(self, event_logger, mock_services):
        mock_services.core.state_manager.get_summary.return_value = {
            "completed": 2,
            "skipped": 1,
            "failed": 0,
        }

        with patch(FIRE_EVENT_PATH) as mock_fire:
            event_logger.finalize_workflow(elapsed_time=5.0)

        event = mock_fire.call_args[0][0]
        assert isinstance(event, WorkflowCompleteEvent)
        assert event.workflow_name == "test_workflow"
        assert event.actions_completed == 2
        assert event.actions_skipped == 1
        assert event.actions_failed == 0
        assert event.elapsed_time == 5.0

    def test_calls_manifest_manager(self, event_logger, mock_services):
        mock_services.core.state_manager.get_summary.return_value = {}

        with patch(FIRE_EVENT_PATH):
            event_logger.finalize_workflow()

        mock_services.support.manifest_manager.mark_workflow_completed.assert_called_once()


# ── handle_workflow_error ──────────────────────────────────────────────


class TestHandleWorkflowError:
    def test_fires_workflow_failed_event(self, event_logger):
        error = RuntimeError("workflow died")
        mgr = MagicMock()
        mgr.get_context.return_value = "agent_a"

        with (
            patch(FIRE_EVENT_PATH) as mock_fire,
            patch(GET_MANAGER_PATH, return_value=mgr),
            patch(GET_ERROR_DETAIL_PATH, return_value="detail"),
        ):
            event_logger.handle_workflow_error(error, elapsed_time=3.0)

        event = mock_fire.call_args[0][0]
        assert isinstance(event, WorkflowFailedEvent)
        assert event.workflow_name == "test_workflow"
        assert event.error_type == "RuntimeError"
        assert event.error_message == "workflow died"
        assert event.error_detail == "detail"
        assert event.elapsed_time == 3.0
        assert event.failed_action == "agent_a"

    def test_calls_manifest_manager_failed(self, event_logger, mock_services):
        error = RuntimeError("boom")
        mgr = MagicMock()
        mgr.get_context.return_value = ""

        with (
            patch(FIRE_EVENT_PATH),
            patch(GET_MANAGER_PATH, return_value=mgr),
            patch(GET_ERROR_DETAIL_PATH, return_value="detail"),
        ):
            event_logger.handle_workflow_error(error)

        mock_services.support.manifest_manager.mark_workflow_failed.assert_called_once()

    def test_marks_running_as_failed(self, event_logger, mock_services):
        error = RuntimeError("boom")
        mgr = MagicMock()
        mgr.get_context.return_value = ""

        with (
            patch(FIRE_EVENT_PATH),
            patch(GET_MANAGER_PATH, return_value=mgr),
            patch(GET_ERROR_DETAIL_PATH, return_value="detail"),
        ):
            event_logger.handle_workflow_error(error)

        mock_services.core.state_manager.mark_running_as_failed.assert_called_once()

    def test_sets_already_displayed(self, event_logger):
        error = RuntimeError("boom")
        mgr = MagicMock()
        mgr.get_context.return_value = ""

        with (
            patch(FIRE_EVENT_PATH),
            patch(GET_MANAGER_PATH, return_value=mgr),
            patch(GET_ERROR_DETAIL_PATH, return_value="detail"),
        ):
            event_logger.handle_workflow_error(error)

        assert error._already_displayed is True
