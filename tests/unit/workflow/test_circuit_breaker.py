"""Tests for ActionExecutor circuit breaker methods."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.storage.backend import DISPOSITION_FAILED, NODE_LEVEL_RECORD_ID
from agent_actions.workflow.executor import (
    ActionExecutionResult,
    ActionExecutor,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager


@pytest.fixture
def mock_deps():
    """Create mock dependencies for ActionExecutor."""
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
    deps.action_runner = MagicMock()
    deps.skip_evaluator = MagicMock(spec=SkipEvaluator)
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.action_runner.execution_order = ["agent_a", "agent_b", "agent_c"]
    return deps


@pytest.fixture
def executor(mock_deps):
    """Create executor with mock dependencies."""
    return ActionExecutor(mock_deps)


class TestCheckUpstreamHealth:
    """Tests for _check_upstream_health()."""

    def test_no_dependencies_returns_none(self, executor):
        """No dependencies means all healthy — returns None."""
        config = {"dependencies": []}
        result = executor._check_upstream_health("agent_b", config)
        assert result is None

    def test_no_dependencies_key_returns_none(self, executor):
        """Missing dependencies key means all healthy — returns None."""
        config = {}
        result = executor._check_upstream_health("agent_b", config)
        assert result is None

    def test_all_deps_healthy_returns_none(self, executor, mock_deps):
        """All dependencies healthy — returns None."""
        mock_deps.state_manager.is_failed.return_value = False
        mock_deps.action_runner.storage_backend = None

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result is None

    def test_dep_failed_via_state_manager(self, executor, mock_deps):
        """One dep failed (state_manager.is_failed) returns dep name."""
        mock_deps.state_manager.is_failed.return_value = True

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result == "agent_a"

    def test_dep_failed_via_disposition(self, executor, mock_deps):
        """One dep has DISPOSITION_FAILED in storage returns dep name."""
        mock_deps.state_manager.is_failed.return_value = False
        storage = MagicMock()
        storage.has_disposition.return_value = True
        mock_deps.action_runner.storage_backend = storage

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)

        assert result == "agent_a"
        storage.has_disposition.assert_called_once_with(
            "agent_a", DISPOSITION_FAILED, record_id=NODE_LEVEL_RECORD_ID
        )

    def test_no_storage_backend_only_checks_state_manager(self, executor, mock_deps):
        """No storage backend — only checks state_manager."""
        mock_deps.state_manager.is_failed.return_value = False
        mock_deps.action_runner.storage_backend = None

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result is None


class TestHandleDependencySkip:
    """Tests for _handle_dependency_skip()."""

    @patch("agent_actions.workflow.executor.fire_event")
    def test_updates_state_to_failed(self, mock_fire, executor, mock_deps):
        """Updates state to 'failed'."""
        mock_deps.action_runner.storage_backend = None
        start_time = datetime.now()

        executor._handle_dependency_skip("agent_b", 1, {}, start_time, "agent_a")

        mock_deps.state_manager.update_status.assert_called_once_with("agent_b", "failed")

    @patch("agent_actions.workflow.executor.fire_event")
    def test_writes_failed_disposition(self, mock_fire, executor, mock_deps):
        """Writes DISPOSITION_FAILED to storage."""
        storage = MagicMock()
        mock_deps.action_runner.storage_backend = storage
        start_time = datetime.now()

        executor._handle_dependency_skip("agent_b", 1, {}, start_time, "agent_a")

        storage.set_disposition.assert_called_once()
        call_kwargs = storage.set_disposition.call_args
        assert call_kwargs[1]["disposition"] == DISPOSITION_FAILED
        assert call_kwargs[1]["action_name"] == "agent_b"

    @patch("agent_actions.workflow.executor.fire_event")
    def test_fires_action_skip_event(self, mock_fire, executor, mock_deps):
        """Fires ActionSkipEvent with correct reason."""
        mock_deps.action_runner.storage_backend = None
        start_time = datetime.now()

        executor._handle_dependency_skip("agent_b", 1, {}, start_time, "agent_a")

        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        from agent_actions.logging.events import ActionSkipEvent

        assert isinstance(event, ActionSkipEvent)
        assert "agent_a" in event.skip_reason

    @patch("agent_actions.workflow.executor.fire_event")
    def test_records_in_run_tracker_if_available(self, mock_fire, executor, mock_deps):
        """Records in run_tracker if available."""
        mock_deps.action_runner.storage_backend = None
        executor.run_tracker = MagicMock()
        executor.run_id = "run-123"
        start_time = datetime.now()

        executor._handle_dependency_skip("agent_b", 1, {}, start_time, "agent_a")

        executor.run_tracker.record_action_complete.assert_called_once()
        config = executor.run_tracker.record_action_complete.call_args[1]["config"]
        assert config.status == "skipped"
        assert config.run_id == "run-123"

    @patch("agent_actions.workflow.executor.fire_event")
    def test_returns_skipped_result(self, mock_fire, executor, mock_deps):
        """Returns ActionExecutionResult(success=True, status='skipped')."""
        mock_deps.action_runner.storage_backend = None
        start_time = datetime.now()

        result = executor._handle_dependency_skip("agent_b", 1, {}, start_time, "agent_a")

        assert isinstance(result, ActionExecutionResult)
        assert result.success is True
        assert result.status == "skipped"


class TestWriteFailedDisposition:
    """Tests for _write_failed_disposition()."""

    def test_writes_disposition_when_storage_available(self, executor, mock_deps):
        """Writes disposition when storage backend is available."""
        storage = MagicMock()
        mock_deps.action_runner.storage_backend = storage

        executor._write_failed_disposition("agent_a", "Some error")

        storage.set_disposition.assert_called_once_with(
            action_name="agent_a",
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_FAILED,
            reason="Some error",
        )

    def test_logs_warning_on_storage_error(self, executor, mock_deps, caplog):
        """Logs warning on storage error (doesn't raise)."""
        storage = MagicMock()
        storage.set_disposition.side_effect = RuntimeError("DB error")
        mock_deps.action_runner.storage_backend = storage

        # Should not raise
        executor._write_failed_disposition("agent_a", "Some error")

    def test_noops_when_storage_backend_is_none(self, executor, mock_deps):
        """No-ops when storage backend is None."""
        mock_deps.action_runner.storage_backend = None

        # Should not raise; nothing happens
        executor._write_failed_disposition("agent_a", "Some error")
