"""Tests for storage error propagation in _resolve_completion_status.

Verifies that storage errors (sqlite3.OperationalError, etc.) propagate
instead of being silently caught and returning COMPLETED.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

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
    deps.action_runner.execution_order = ["agent_a"]
    deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
    return deps


@pytest.fixture
def executor(mock_deps):
    return ActionExecutor(mock_deps)


class TestResolveCompletionStatusStorageErrors:
    def test_operational_error_from_has_disposition_propagates(self, executor, mock_deps):
        mock_deps.action_runner.storage_backend.has_disposition.side_effect = (
            sqlite3.OperationalError("database is locked")
        )
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            executor._resolve_completion_status("agent_a")

    def test_operational_error_from_get_failed_items_propagates(self, executor, mock_deps):
        mock_deps.action_runner.storage_backend.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend.get_failed_items.side_effect = (
            sqlite3.OperationalError("database is locked")
        )
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            executor._resolve_completion_status("agent_a")

    def test_no_storage_backend_returns_completed(self, executor, mock_deps):
        mock_deps.action_runner.storage_backend = None
        result = executor._resolve_completion_status("agent_a")
        assert result == ActionStatus.COMPLETED

    def test_normal_completed_still_works(self, executor, mock_deps):
        mock_deps.action_runner.storage_backend.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend.get_failed_items.return_value = []
        result = executor._resolve_completion_status("agent_a")
        assert result == ActionStatus.COMPLETED

    def test_completed_with_failures_still_works(self, executor, mock_deps):
        mock_deps.action_runner.storage_backend.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend.get_failed_items.return_value = [
            {"record_id": "abc123", "reason": "LLM error"}
        ]
        mock_deps.action_runner.storage_backend.has_successful_items.return_value = True
        result = executor._resolve_completion_status("agent_a")
        assert result == ActionStatus.COMPLETED_WITH_FAILURES
