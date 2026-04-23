"""Tests for ActionExecutor lifecycle: execute_action_sync and helper methods."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.logging.events.batch_events import BatchCompleteEvent, BatchSubmittedEvent
from agent_actions.workflow.executor import (
    ActionExecutionResult,
    ActionExecutor,
    ActionRunParams,
    ExecutionMetrics,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


@pytest.fixture
def mock_deps():
    """Create mock dependencies with spec= on sub-mocks to catch typos."""
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
    deps.action_runner = MagicMock()
    deps.skip_evaluator = MagicMock(spec=SkipEvaluator)
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.action_runner.workflow_name = "test_workflow"
    deps.action_runner.get_action_folder.return_value = "/tmp/agent_io"
    deps.action_runner.execution_order = ["agent_a", "agent_b"]
    # Default: no item-level failures (so actions complete as "completed", not "completed_with_failures")
    deps.action_runner.storage_backend.get_failed_items.return_value = []
    # Default: no guard-all-skipped disposition
    deps.action_runner.storage_backend.has_disposition.return_value = False
    # Default status details for limit-change detection (no limits stored)
    deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
    return deps


@pytest.fixture
def executor(mock_deps):
    """Create executor with mock dependencies."""
    return ActionExecutor(mock_deps)


# ── execute_action_sync ─────────────────────────────────────────────────


class TestExecuteAgentSync:
    """Tests for the top-level execute_action_sync 5-branch flow."""

    def test_completed_with_output_skips(self, executor, mock_deps):
        """Already-completed agent with output files should be skipped."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        storage = MagicMock()
        storage.list_target_files.return_value = ["file1.json"]
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        result = executor.execute_action_sync(
            "agent_a", action_idx=0, action_config={}, is_last_action=False
        )

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED
        mock_deps.action_runner.run_action.assert_not_called()

    def test_completed_no_output_reruns(self, executor, mock_deps):
        """Completed agent with no output files should be re-run.

        Flow: get_status returns "completed" → _verify_completion_status finds no files
        → resets to "pending" and returns (False, None) → execution falls through to
        skip evaluation → _execute_action_run. get_status is only called once at the
        top of execute_action_sync.
        """
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        storage = MagicMock()
        storage.list_target_files.return_value = []
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        mock_deps.skip_evaluator.should_skip_action.return_value = False
        mock_deps.action_runner.run_action.return_value = "/output"
        mock_deps.output_manager.setup_correlation_wrapper.return_value = None
        mock_deps.batch_manager.check_batch_submission.return_value = None

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor.execute_action_sync(
                "agent_a", action_idx=0, action_config={}, is_last_action=False
            )

        assert result.success is True
        mock_deps.state_manager.update_status.assert_any_call("agent_a", ActionStatus.PENDING)

    def test_storage_error_during_verify_reruns_agent(self, executor, mock_deps):
        """Storage error during verification should reset to pending and re-run the agent.

        Flow: get_status returns "completed" → _verify_completion_status hits OSError
        → resets to "pending" and returns (False, None) → execution falls through to
        skip evaluation → _execute_action_run.
        """
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        storage = MagicMock()
        storage.list_target_files.side_effect = OSError("SQLite lock")
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        mock_deps.skip_evaluator.should_skip_action.return_value = False
        mock_deps.action_runner.run_action.return_value = "/output"
        mock_deps.output_manager.setup_correlation_wrapper.return_value = None
        mock_deps.batch_manager.check_batch_submission.return_value = None

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor.execute_action_sync(
                "agent_a", action_idx=0, action_config={}, is_last_action=False
            )

        assert result.success is True
        mock_deps.state_manager.update_status.assert_any_call("agent_a", ActionStatus.PENDING)
        mock_deps.skip_evaluator.should_skip_action.assert_called_once()
        mock_deps.action_runner.run_action.assert_called_once()

    def test_batch_submitted_dispatches(self, executor, mock_deps):
        """Batch_submitted status should dispatch to batch check handler."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")

        with patch("agent_actions.workflow.executor.fire_event"):
            result = executor.execute_action_sync(
                "agent_a", action_idx=0, action_config={}, is_last_action=False
            )

        assert result.status == ActionStatus.COMPLETED
        mock_deps.batch_manager.handle_batch_agent.assert_called_once()

    def test_batch_in_progress_returns_batch_submitted(self, executor, mock_deps):
        """Batch in_progress should return batch_submitted and fire BatchSubmittedEvent."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = (None, "in_progress")

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor.execute_action_sync(
                "agent_a",
                action_idx=0,
                action_config={"batch_id": "b1", "model_vendor": "openai"},
                is_last_action=False,
            )

        assert result.success is True
        assert result.status == ActionStatus.BATCH_SUBMITTED
        mock_deps.state_manager.update_status.assert_any_call(
            "agent_a", ActionStatus.BATCH_SUBMITTED
        )
        event = mock_fire.call_args[0][0]
        assert isinstance(event, BatchSubmittedEvent)

    def test_batch_failed_returns_failed(self, executor, mock_deps):
        """Batch failure should mark failed and fire BatchCompleteEvent with failed=1."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = (None, "failed")

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor.execute_action_sync(
                "agent_a",
                action_idx=0,
                action_config={"batch_id": "b2"},
                is_last_action=False,
            )

        assert result.success is False
        assert result.status == ActionStatus.FAILED
        fail_calls = [
            c
            for c in mock_deps.state_manager.update_status.call_args_list
            if c[0][1] == ActionStatus.FAILED
        ]
        assert len(fail_calls) >= 1
        assert fail_calls[0][0][0] == "agent_a"
        event = mock_fire.call_args[0][0]
        assert isinstance(event, BatchCompleteEvent)
        assert event.failed == 1
        assert event.completed == 0

    def test_skip_evaluator_marks_completed(self, executor, mock_deps):
        """When skip evaluator says skip, should mark completed without copying data."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.PENDING
        mock_deps.skip_evaluator.should_skip_action.return_value = True

        with patch("agent_actions.workflow.executor.fire_event"):
            result = executor.execute_action_sync(
                "agent_a", action_idx=0, action_config={"agent_type": "a"}, is_last_action=False
            )

        assert result.status == ActionStatus.COMPLETED

    def test_normal_path_runs_agent(self, executor, mock_deps):
        """Normal pending agent should go through _execute_action_run."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.PENDING
        mock_deps.skip_evaluator.should_skip_action.return_value = False
        mock_deps.action_runner.run_action.return_value = "/output"
        mock_deps.output_manager.setup_correlation_wrapper.return_value = None
        mock_deps.batch_manager.check_batch_submission.return_value = None

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor.execute_action_sync(
                "agent_a", action_idx=0, action_config={}, is_last_action=False
            )

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED
        mock_deps.action_runner.run_action.assert_called_once()

    def test_run_failure_marks_failed(self, executor, mock_deps):
        """Exception during agent run should mark failed and return error."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.PENDING
        mock_deps.skip_evaluator.should_skip_action.return_value = False
        mock_deps.action_runner.run_action.side_effect = RuntimeError("agent crashed")
        mock_deps.output_manager.setup_correlation_wrapper.return_value = None

        result = executor.execute_action_sync(
            "agent_a", action_idx=0, action_config={}, is_last_action=False
        )

        assert result.success is False
        assert result.status == ActionStatus.FAILED
        assert isinstance(result.error, RuntimeError)
        fail_calls = [
            c
            for c in mock_deps.state_manager.update_status.call_args_list
            if c[0][1] == ActionStatus.FAILED
        ]
        assert len(fail_calls) == 1
        assert fail_calls[0][0][0] == "agent_a"

    def test_no_storage_backend_skips_verification(self, executor, mock_deps):
        """Completed agent with no storage_backend should skip (no files to verify)."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.action_runner.storage_backend = None

        result = executor.execute_action_sync(
            "agent_a", action_idx=0, action_config={}, is_last_action=False
        )

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED


# ── _handle_run_success ────────────────────────────────────────────────


class TestHandleRunSuccess:
    """Tests for _handle_run_success branch logic."""

    def _make_params(self, **overrides):
        defaults = {
            "action_name": "agent_a",
            "action_idx": 0,
            "action_config": {},
            "is_last_action": False,
            "start_time": datetime.now(),
        }
        defaults.update(overrides)
        return ActionRunParams(**defaults)

    def test_batch_submitted_status(self, executor, mock_deps):
        """batch_submitted batch_status should return batch_submitted result with timestamp."""
        params = self._make_params()
        with patch("agent_actions.workflow.executor.fire_event"):
            result = executor._handle_run_success(params, "/out", 1.0, "batch_submitted")

        assert result.status == ActionStatus.BATCH_SUBMITTED
        call_args = mock_deps.state_manager.update_status.call_args
        assert call_args[0] == ("agent_a", ActionStatus.BATCH_SUBMITTED)
        assert "batch_submitted_at" in call_args[1]  # timestamp persisted

    def test_passthrough_status(self, executor, mock_deps):
        """passthrough batch_status should mark completed."""
        params = self._make_params()
        result = executor._handle_run_success(params, "/out", 1.0, "passthrough")

        assert result.status == ActionStatus.COMPLETED
        assert result.output_folder == "/out"
        mock_deps.state_manager.update_status.assert_called_with(
            "agent_a", ActionStatus.COMPLETED, record_limit=None, file_limit=None
        )

    def test_normal_completion_with_tokens(self, executor, mock_deps):
        """Normal completion should capture tokens and model info."""
        params = self._make_params(action_config={"model_vendor": "openai", "model_name": "gpt-4"})
        with patch(
            "agent_actions.workflow.executor.get_last_usage",
            return_value={"total_tokens": 100},
        ):
            result = executor._handle_run_success(params, "/out", 2.5, None)

        assert result.status == ActionStatus.COMPLETED
        assert result.metrics.tokens == {"total_tokens": 100}
        assert result.metrics.model_vendor == "openai"
        assert result.metrics.model_name == "gpt-4"

    def test_model_info_in_metrics(self, executor, mock_deps):
        """Model vendor/name from agent_config should appear in metrics."""
        params = self._make_params(
            action_config={"model_vendor": "anthropic", "model_name": "claude"}
        )
        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor._handle_run_success(params, "/out", 1.0, None)

        assert result.metrics.model_vendor == "anthropic"
        assert result.metrics.model_name == "claude"

    def test_guard_all_skipped_returns_skipped(self, executor, mock_deps):
        """When all records are guard-skipped, status should be 'skipped' and ActionSkipEvent fired."""
        mock_deps.action_runner.storage_backend.has_disposition.return_value = True
        mock_deps.action_runner.storage_backend.list_target_files.return_value = []
        params = self._make_params()

        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor._handle_run_success(params, "/out", 1.0, None)

        assert result.success is True
        assert result.status == ActionStatus.SKIPPED
        assert result.output_folder == "/out"
        call_args = mock_deps.state_manager.update_status.call_args
        assert call_args[0] == ("agent_a", ActionStatus.SKIPPED)
        assert "skip_reason" in call_args[1]

        from agent_actions.logging.events import ActionSkipEvent

        skip_events = [
            call for call in mock_fire.call_args_list if isinstance(call[0][0], ActionSkipEvent)
        ]
        assert len(skip_events) == 1
        assert skip_events[0][0][0].skip_reason == "All records guard-skipped"
        assert skip_events[0][0][0].action_index == 0
        assert skip_events[0][0][0].total_actions == 2  # from execution_order fixture

    def test_guard_all_skipped_records_in_run_tracker(self, executor, mock_deps):
        """Guard-all-skipped should record in run_tracker with skip_reason."""
        mock_deps.action_runner.storage_backend.has_disposition.return_value = True
        mock_deps.action_runner.storage_backend.list_target_files.return_value = []
        executor.run_tracker = MagicMock()
        executor.run_id = "run-123"
        params = self._make_params()

        with patch("agent_actions.workflow.executor.fire_event"):
            result = executor._handle_run_success(params, "/out", 1.0, None)

        assert result.status == ActionStatus.SKIPPED
        executor.run_tracker.record_action_complete.assert_called_once()
        call_kwargs = executor.run_tracker.record_action_complete.call_args
        config = call_kwargs[1]["config"] if "config" in call_kwargs[1] else call_kwargs[0][0]
        assert config.status == "skipped"
        assert config.skip_reason == "All records guard-skipped"


# ── _handle_run_failure ────────────────────────────────────────────────


class TestHandleRunFailure:
    """Tests for _handle_run_failure."""

    def test_marks_failed_and_returns_error(self, executor, mock_deps):
        error = ValueError("test error")
        params = ActionRunParams(
            action_name="agent_a",
            action_idx=0,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )
        result = executor._handle_run_failure(params, error)

        assert result.success is False
        assert result.status == ActionStatus.FAILED
        assert result.error is error
        call_args = mock_deps.state_manager.update_status.call_args
        assert call_args[0] == ("agent_a", ActionStatus.FAILED)
        assert "error_message" in call_args[1]

    def test_records_in_run_tracker_when_available(self, executor, mock_deps):
        """When run_tracker + run_id are set, should record action complete."""
        executor.run_tracker = MagicMock()
        executor.run_id = "run_123"
        error = RuntimeError("fail")
        params = ActionRunParams(
            action_name="agent_a",
            action_idx=0,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )

        with patch("agent_actions.workflow.executor.get_error_detail", return_value="detail"):
            executor._handle_run_failure(params, error)

        executor.run_tracker.record_action_complete.assert_called_once()


# ── _execute_action_run ─────────────────────────────────────────────────


class TestExecuteAgentRun:
    """Tests for _execute_action_run lifecycle."""

    def test_status_transitions_running_to_completed(self, executor, mock_deps):
        """Should transition from running → completed on success."""
        mock_deps.action_runner.run_action.return_value = "/output"
        mock_deps.output_manager.setup_correlation_wrapper.return_value = None
        mock_deps.batch_manager.check_batch_submission.return_value = None
        params = ActionRunParams(
            action_name="agent_a",
            action_idx=0,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor._execute_action_run(params)

        assert result.success is True
        mock_deps.state_manager.update_status.assert_any_call("agent_a", ActionStatus.RUNNING)

    def test_failure_calls_handle_run_failure(self, executor, mock_deps):
        """Exception should result in _handle_run_failure path."""
        mock_deps.action_runner.run_action.side_effect = RuntimeError("boom")
        mock_deps.output_manager.setup_correlation_wrapper.return_value = None
        params = ActionRunParams(
            action_name="agent_a",
            action_idx=0,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )

        result = executor._execute_action_run(params)

        assert result.success is False
        assert result.status == ActionStatus.FAILED

    def test_correlation_setup_and_cleanup(self, executor, mock_deps):
        """Correlation wrapper should be set up and cleaned up."""
        original_fn = MagicMock()
        mock_deps.action_runner.setup_directories = original_fn
        wrapper = MagicMock()
        mock_deps.output_manager.setup_correlation_wrapper.return_value = wrapper
        mock_deps.action_runner.run_action.return_value = "/output"
        mock_deps.batch_manager.check_batch_submission.return_value = None
        params = ActionRunParams(
            action_name="agent_a",
            action_idx=0,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            executor._execute_action_run(params)

        # Correlation wrapper was installed, then original restored
        assert mock_deps.action_runner.setup_directories == original_fn


# ── _verify_completion_status ──────────────────────────────────────────


class TestVerifyCompletionStatus:
    """Tests for _verify_completion_status output verification."""

    def test_with_files_returns_skip(self, executor, mock_deps):
        """Agent with output files should be skipped (already done)."""
        storage = MagicMock()
        storage.list_target_files.return_value = ["file.json"]
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        should_skip, result = executor._verify_completion_status("agent_a")

        assert should_skip is True
        assert result.success is True

    def test_no_files_resets_to_pending(self, executor, mock_deps):
        """Agent with no output files should be reset to pending."""
        storage = MagicMock()
        storage.list_target_files.return_value = []
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        should_skip, result = executor._verify_completion_status("agent_a")

        assert should_skip is False
        assert result is None
        mock_deps.state_manager.update_status.assert_called_with("agent_a", ActionStatus.PENDING)

    @pytest.mark.parametrize(
        "exc",
        [
            OSError("storage down"),
            ValueError("Invalid action_name"),
            RuntimeError("backend not initialized"),
        ],
        ids=["OSError", "ValueError", "RuntimeError"],
    )
    def test_storage_error_resets_to_pending(self, executor, mock_deps, exc):
        """Any exception during verification should reset to pending and re-run."""
        storage = MagicMock()
        storage.list_target_files.side_effect = exc
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        should_skip, result = executor._verify_completion_status("agent_a")

        assert should_skip is False
        assert result is None
        mock_deps.state_manager.update_status.assert_called_with("agent_a", ActionStatus.PENDING)

    def test_no_backend_returns_skip(self, executor, mock_deps):
        """No storage backend should skip (trust the status)."""
        mock_deps.action_runner.storage_backend = None

        should_skip, result = executor._verify_completion_status("agent_a")

        assert should_skip is True
        assert result.success is True


# ── _handle_action_skip ─────────────────────────────────────────────────


class TestHandleAgentSkip:
    """Tests for _handle_action_skip."""

    def test_marks_completed_and_fires_event(self, executor, mock_deps):
        """Should mark completed and fire skip event without copying data."""
        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            result = executor._handle_action_skip("agent_a", 0, {}, datetime.now())

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED
        mock_deps.state_manager.update_status.assert_called_with(
            "agent_a", ActionStatus.COMPLETED, record_limit=None, file_limit=None
        )
        mock_fire.assert_called_once()

    def test_state_manager_and_result_status_agree(self, executor, mock_deps):
        """Regression: state_manager.update_status and result.status must agree."""
        with patch("agent_actions.workflow.executor.fire_event"):
            result = executor._handle_action_skip("agent_a", 0, {}, datetime.now())

        status_mgr_call = mock_deps.state_manager.update_status.call_args
        assert status_mgr_call[0][1] == result.status == ActionStatus.COMPLETED

    def test_skip_does_not_use_output_manager(self, executor, mock_deps):
        """WHERE-clause skip does not interact with output manager."""
        with patch("agent_actions.workflow.executor.fire_event"):
            executor._handle_action_skip("agent_a", 0, {}, datetime.now())

        assert mock_deps.output_manager.method_calls == []

    def test_total_agents_from_execution_order(self, executor, mock_deps):
        """total_agents should come from agent_runner.execution_order length."""
        with patch("agent_actions.workflow.executor.fire_event") as mock_fire:
            executor._handle_action_skip("agent_a", 0, {}, datetime.now())

        event = mock_fire.call_args[0][0]
        assert event.total_actions == 2  # ["agent_a", "agent_b"]


# ── _track_action_start ───────────────────────────────────────────────


class TestTrackActionStart:
    """Tests for _track_action_start action type detection."""

    def _make_params(self, action_config):
        return ActionRunParams(
            action_name="agent_a",
            action_idx=0,
            action_config=action_config,
            is_last_action=False,
            start_time=datetime.now(),
        )

    def test_tool_action_type(self, executor):
        """model_vendor='tool' should produce action_type='tool'."""
        executor.run_tracker = MagicMock()
        executor.run_id = "run_1"
        executor._track_action_start(self._make_params({"model_vendor": "tool"}))

        call_kwargs = executor.run_tracker.record_action_start.call_args[1]
        assert call_kwargs["action_type"] == "tool"

    def test_hitl_action_type(self, executor):
        """kind='hitl' should produce action_type='hitl'."""
        executor.run_tracker = MagicMock()
        executor.run_id = "run_1"
        executor._track_action_start(self._make_params({"kind": "hitl"}))

        call_kwargs = executor.run_tracker.record_action_start.call_args[1]
        assert call_kwargs["action_type"] == "hitl"

    def test_llm_action_type_default(self, executor):
        """Default action type should be 'llm'."""
        executor.run_tracker = MagicMock()
        executor.run_id = "run_1"
        executor._track_action_start(self._make_params({}))

        call_kwargs = executor.run_tracker.record_action_start.call_args[1]
        assert call_kwargs["action_type"] == "llm"


# ── ActionExecutionResult ──────────────────────────────────────────────


class TestActionExecutionResult:
    """Tests for result dataclass behavior."""

    def test_default_metrics(self):
        result = ActionExecutionResult(success=True)
        assert result.metrics is not None
        assert result.duration == 0.0

    def test_backward_compat_properties(self):
        metrics = ExecutionMetrics(duration=1.5, tokens={"total": 10}, model_vendor="x")
        result = ActionExecutionResult(success=True, metrics=metrics)
        assert result.duration == 1.5
        assert result.tokens == {"total": 10}
        assert result.model_vendor == "x"

    def test_repr(self):
        result = ActionExecutionResult(success=True)
        assert "success=True" in repr(result)
