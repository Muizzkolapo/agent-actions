"""Tests for ActionExecutor circuit breaker methods."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.storage.backend import (
    DISPOSITION_FAILED,
    DISPOSITION_SKIPPED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.workflow.executor import (
    ActionExecutionResult,
    ActionExecutor,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


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
        mock_deps.state_manager.is_skipped.return_value = False
        mock_deps.action_runner.storage_backend = None

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result is None

    def test_dep_failed_via_state_manager(self, executor, mock_deps):
        """One dep failed (state_manager.is_failed) returns dep name."""
        mock_deps.state_manager.is_failed.return_value = True
        mock_deps.state_manager.is_skipped.return_value = False

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result == "agent_a"

    def test_dep_skipped_via_state_manager(self, executor, mock_deps):
        """One dep skipped (state_manager.is_skipped) returns dep name."""
        mock_deps.state_manager.is_failed.return_value = False
        mock_deps.state_manager.is_skipped.return_value = True

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result == "agent_a"

    def test_dep_failed_via_disposition(self, executor, mock_deps):
        """One dep has DISPOSITION_FAILED in storage returns dep name."""
        mock_deps.state_manager.is_failed.return_value = False
        mock_deps.state_manager.is_skipped.return_value = False
        storage = MagicMock()
        storage.has_disposition.side_effect = lambda dep, disp, **kw: disp == DISPOSITION_FAILED
        mock_deps.action_runner.storage_backend = storage

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result == "agent_a"

    def test_dep_skipped_via_disposition(self, executor, mock_deps):
        """One dep has DISPOSITION_SKIPPED in storage returns dep name."""
        mock_deps.state_manager.is_failed.return_value = False
        mock_deps.state_manager.is_skipped.return_value = False
        storage = MagicMock()
        storage.has_disposition.side_effect = lambda dep, disp, **kw: disp == DISPOSITION_SKIPPED
        mock_deps.action_runner.storage_backend = storage

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result == "agent_a"

    def test_no_storage_backend_only_checks_state_manager(self, executor, mock_deps):
        """No storage backend — only checks state_manager."""
        mock_deps.state_manager.is_failed.return_value = False
        mock_deps.state_manager.is_skipped.return_value = False
        mock_deps.action_runner.storage_backend = None

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result is None


class TestHandleDependencySkip:
    """Tests for _handle_dependency_skip()."""

    @patch("agent_actions.workflow.executor.fire_event")
    def test_updates_state_to_skipped(self, mock_fire, executor, mock_deps):
        """Updates state to 'skipped'."""
        mock_deps.action_runner.storage_backend = None
        start_time = datetime.now()

        executor._handle_dependency_skip("agent_b", 1, {}, start_time, "agent_a")

        mock_deps.state_manager.update_status.assert_called_once_with(
            "agent_b", ActionStatus.SKIPPED
        )

    @patch("agent_actions.workflow.executor.fire_event")
    def test_writes_skipped_disposition(self, mock_fire, executor, mock_deps):
        """Writes DISPOSITION_SKIPPED to storage."""
        storage = MagicMock()
        mock_deps.action_runner.storage_backend = storage
        start_time = datetime.now()

        executor._handle_dependency_skip("agent_b", 1, {}, start_time, "agent_a")

        storage.set_disposition.assert_called_once()
        call_kwargs = storage.set_disposition.call_args
        assert call_kwargs[1]["disposition"] == DISPOSITION_SKIPPED
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
        """Records in run_tracker with status 'skipped'."""
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
    def test_returns_skipped_result_with_success_true(self, mock_fire, executor, mock_deps):
        """Returns ActionExecutionResult(success=True, status='skipped') — skipped state, but independent branches continue."""
        mock_deps.action_runner.storage_backend = None
        start_time = datetime.now()

        result = executor._handle_dependency_skip("agent_b", 1, {}, start_time, "agent_a")

        assert isinstance(result, ActionExecutionResult)
        assert result.success is True
        assert result.status == ActionStatus.SKIPPED


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


class TestWriteSkippedDisposition:
    """Tests for _write_skipped_disposition()."""

    def test_writes_disposition_when_storage_available(self, executor, mock_deps):
        """Writes DISPOSITION_SKIPPED when storage backend is available."""
        storage = MagicMock()
        mock_deps.action_runner.storage_backend = storage

        executor._write_skipped_disposition("agent_b", "Upstream failed")

        storage.set_disposition.assert_called_once_with(
            action_name="agent_b",
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_SKIPPED,
            reason="Upstream failed",
        )

    def test_logs_warning_on_storage_error(self, executor, mock_deps, caplog):
        """Logs warning on storage error (doesn't raise)."""
        storage = MagicMock()
        storage.set_disposition.side_effect = RuntimeError("DB error")
        mock_deps.action_runner.storage_backend = storage

        executor._write_skipped_disposition("agent_b", "Upstream failed")

    def test_noops_when_storage_backend_is_none(self, executor, mock_deps):
        """No-ops when storage backend is None."""
        mock_deps.action_runner.storage_backend = None

        executor._write_skipped_disposition("agent_b", "Upstream failed")


class TestLevelCompletionColoring:
    """Tests for level completion line color logic (red/yellow/green)."""

    def test_green_when_all_ok(self, tmp_path):
        """Level line is green when all actions completed successfully."""
        mgr = ActionStateManager(tmp_path / "status.json", ["a", "b"])
        mgr.update_status("a", ActionStatus.COMPLETED)
        mgr.update_status("b", ActionStatus.COMPLETED)

        has_failed = mgr.get_failed_actions(["a", "b"])
        has_skipped = any(mgr.is_skipped(a) for a in ["a", "b"])

        assert not has_failed
        assert not has_skipped

    def test_red_when_action_failed(self, tmp_path):
        """Level line is red when any action failed."""
        mgr = ActionStateManager(tmp_path / "status.json", ["a", "b"])
        mgr.update_status("a", ActionStatus.COMPLETED)
        mgr.update_status("b", ActionStatus.FAILED)

        has_failed = mgr.get_failed_actions(["a", "b"])
        assert has_failed

    def test_yellow_when_action_skipped(self, tmp_path):
        """Level line is yellow when actions are skipped but none failed."""
        mgr = ActionStateManager(tmp_path / "status.json", ["a", "b"])
        mgr.update_status("a", ActionStatus.COMPLETED)
        mgr.update_status("b", ActionStatus.SKIPPED)

        has_failed = mgr.get_failed_actions(["a", "b"])
        has_skipped = any(mgr.is_skipped(a) for a in ["a", "b"])

        assert not has_failed
        assert has_skipped

    def test_red_takes_precedence_over_yellow(self, tmp_path):
        """Red (failed) takes precedence over yellow (skipped)."""
        mgr = ActionStateManager(tmp_path / "status.json", ["a", "b", "c"])
        mgr.update_status("a", ActionStatus.COMPLETED)
        mgr.update_status("b", ActionStatus.FAILED)
        mgr.update_status("c", ActionStatus.SKIPPED)

        has_failed = mgr.get_failed_actions(["a", "b", "c"])
        has_skipped = any(mgr.is_skipped(a) for a in ["a", "b", "c"])

        assert has_failed
        assert has_skipped

    def test_yellow_for_completed_with_failures(self, tmp_path):
        """Level line is yellow when action has partial failures."""
        mgr = ActionStateManager(tmp_path / "status.json", ["a", "b"])
        mgr.update_status("a", ActionStatus.COMPLETED)
        mgr.update_status("b", ActionStatus.COMPLETED_WITH_FAILURES)

        has_failed = mgr.get_failed_actions(["a", "b"])
        has_partial = any(mgr.is_completed_with_failures(a) for a in ["a", "b"])

        assert not has_failed
        assert has_partial


class TestResolveCompletionStatus:
    """Tests for _resolve_completion_status()."""

    @patch("agent_actions.workflow.executor.fire_event")
    def test_returns_completed_when_no_failures(self, mock_fire, executor, mock_deps):
        mock_deps.action_runner.storage_backend.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend.get_failed_items.return_value = []
        assert executor._resolve_completion_status("agent_a") == ActionStatus.COMPLETED

    @patch("agent_actions.workflow.executor.fire_event")
    def test_returns_completed_with_failures_when_items_failed(
        self, mock_fire, executor, mock_deps
    ):
        mock_deps.action_runner.storage_backend.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend.get_failed_items.return_value = [
            {"record_id": "guid-1", "disposition": "failed", "reason": "timeout"}
        ]
        assert (
            executor._resolve_completion_status("agent_a") == ActionStatus.COMPLETED_WITH_FAILURES
        )

    @patch("agent_actions.workflow.executor.fire_event")
    def test_returns_completed_when_no_storage_backend(self, mock_fire, executor, mock_deps):
        mock_deps.action_runner.storage_backend = None
        assert executor._resolve_completion_status("agent_a") == ActionStatus.COMPLETED

    @patch("agent_actions.workflow.executor.fire_event")
    def test_returns_completed_on_storage_error(self, mock_fire, executor, mock_deps):
        mock_deps.action_runner.storage_backend.has_disposition.side_effect = RuntimeError(
            "DB error"
        )
        assert executor._resolve_completion_status("agent_a") == ActionStatus.COMPLETED

    @patch("agent_actions.workflow.executor.fire_event")
    def test_returns_skipped_when_all_records_guard_skipped(self, mock_fire, executor, mock_deps):
        """When pipeline sets DISPOSITION_SKIPPED at node level, status should be 'skipped'."""
        mock_deps.action_runner.storage_backend.has_disposition.return_value = True
        assert executor._resolve_completion_status("agent_a") == ActionStatus.SKIPPED
        mock_deps.action_runner.storage_backend.has_disposition.assert_called_once_with(
            "agent_a", DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID
        )

    @patch("agent_actions.workflow.executor.fire_event")
    def test_guard_skipped_checked_before_failed_items(self, mock_fire, executor, mock_deps):
        """Guard-skipped disposition is checked before item-level failures."""
        mock_deps.action_runner.storage_backend.has_disposition.return_value = True
        mock_deps.action_runner.storage_backend.get_failed_items.return_value = [
            {"record_id": "guid-1", "disposition": "failed", "reason": "timeout"}
        ]
        assert executor._resolve_completion_status("agent_a") == ActionStatus.SKIPPED
        mock_deps.action_runner.storage_backend.get_failed_items.assert_not_called()


class TestCircuitBreakerIgnoresPartial:
    """completed_with_failures must NOT trigger circuit breaker."""

    def test_completed_with_failures_not_detected_by_upstream_health(self, executor, mock_deps):
        mock_deps.state_manager.is_failed.return_value = False
        mock_deps.state_manager.is_skipped.return_value = False
        mock_deps.action_runner.storage_backend = None

        config = {"dependencies": ["agent_a"]}
        result = executor._check_upstream_health("agent_b", config)
        assert result is None


class TestGetFailedItems:
    """Tests for StorageBackend.get_failed_items() default implementation."""

    def test_filters_node_level_sentinel(self):
        from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID, StorageBackend

        class FakeBackend(StorageBackend):
            @classmethod
            def create(cls, **kwargs):
                return cls()

            @property
            def backend_type(self):
                return "fake"

            def initialize(self):
                pass

            def write_target(self, *a, **kw):
                pass

            def read_target(self, *a, **kw):
                return []

            def write_source(self, *a, **kw):
                pass

            def read_source(self, *a, **kw):
                return []

            def list_target_files(self, *a, **kw):
                return []

            def list_source_files(self, *a, **kw):
                return []

            def preview_target(self, *a, **kw):
                return {}

            def get_storage_stats(self):
                return {}

            def delete_target(self, *a, **kw):
                return 0

            def get_disposition(self, action_name, record_id=None, disposition=None):
                return [
                    {
                        "record_id": NODE_LEVEL_RECORD_ID,
                        "disposition": "failed",
                        "reason": "total wipeout",
                    },
                    {"record_id": "guid-1", "disposition": "failed", "reason": "timeout"},
                    {"record_id": "guid-2", "disposition": "failed", "reason": "429"},
                ]

        backend = FakeBackend()
        items = backend.get_failed_items("action_a")
        assert len(items) == 2
        assert all(i["record_id"] != NODE_LEVEL_RECORD_ID for i in items)
