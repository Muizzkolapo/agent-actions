"""Tests for batch action_name injection in executor batch-check paths.

The batch result processor needs action_name on action_config for
RecordEnvelope.build_content() namespacing. executor.py:827 (sync)
and :913 (async) inject it before calling handle_batch_agent.
If these lines are removed, batch namespacing breaks silently.
"""

from unittest.mock import MagicMock, patch

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
    """Create mock dependencies matching test_executor_lifecycle conventions."""
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
    deps.action_runner = MagicMock()
    deps.skip_evaluator = MagicMock(spec=SkipEvaluator)
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.action_runner.workflow_name = "test_workflow"
    deps.action_runner.get_action_folder.return_value = "/tmp/agent_io"
    deps.action_runner.execution_order = ["my_extract"]
    deps.action_runner.storage_backend.get_failed_items.return_value = []
    deps.action_runner.storage_backend.has_disposition.return_value = False
    deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
    return deps


@pytest.fixture
def executor(mock_deps):
    return ActionExecutor(mock_deps)


class TestBatchActionNameInjectionSync:
    """action_name must be on action_config before handle_batch_agent is called (sync)."""

    def test_batch_check_injects_action_name_into_config(self, executor, mock_deps):
        """Sync batch-check path injects action_name before calling handle_batch_agent."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")

        config = {"kind": "llm"}

        with patch("agent_actions.workflow.executor.fire_event"):
            executor.execute_action_sync(
                "my_extract", action_idx=0, action_config=config, is_last_action=False
            )

        assert config["action_name"] == "my_extract"

    def test_action_name_present_before_handle_batch_agent_called(self, executor, mock_deps):
        """action_name injection must happen BEFORE handle_batch_agent, not after."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        captured_config = {}

        def capture_config(action_name, output_dir, agent_config):
            # Snapshot the config at the moment handle_batch_agent is called
            captured_config.update(agent_config)
            return ("/output", "completed")

        mock_deps.batch_manager.handle_batch_agent.side_effect = capture_config

        with patch("agent_actions.workflow.executor.fire_event"):
            executor.execute_action_sync(
                "my_extract",
                action_idx=0,
                action_config={"kind": "llm"},
                is_last_action=False,
            )

        assert captured_config["action_name"] == "my_extract"


class TestBatchActionNameInjectionAsync:
    """action_name must be on action_config before handle_batch_agent is called (async)."""

    @pytest.mark.asyncio
    async def test_batch_check_async_injects_action_name_into_config(self, executor, mock_deps):
        """Async batch-check path injects action_name before calling handle_batch_agent."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")

        config = {"kind": "llm"}

        with patch("agent_actions.workflow.executor.fire_event"):
            await executor.execute_action_async(
                "my_extract", action_idx=0, action_config=config, is_last_action=False
            )

        assert config["action_name"] == "my_extract"

        call_args = mock_deps.batch_manager.handle_batch_agent.call_args
        passed_config = call_args[0][2]
        assert passed_config["action_name"] == "my_extract"
