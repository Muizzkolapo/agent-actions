"""Tests for batch action_name availability in executor batch-check paths.

The batch result processor needs action_name on action_config for
RecordEnvelope.build_content() namespacing. The coordinator injects
action_name into all action_configs at workflow init time, so it is
always present when the executor runs.
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


class TestBatchActionNamePresent:
    """action_name must be on action_config when handle_batch_agent is called.

    The coordinator injects action_name at workflow init. These tests verify
    the executor correctly passes it through to handle_batch_agent.
    """

    def test_action_name_passed_to_handle_batch_agent_sync(self, executor, mock_deps):
        """Sync batch-check passes action_name through to handle_batch_agent."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        captured_config = {}

        def capture_config(action_name, output_dir, agent_config):
            captured_config.update(agent_config)
            return ("/output", "completed")

        mock_deps.batch_manager.handle_batch_agent.side_effect = capture_config

        # action_name is pre-set by coordinator (not by executor)
        config = {"kind": "llm", "action_name": "my_extract"}

        with patch("agent_actions.workflow.executor.fire_event"):
            executor.execute_action_sync(
                "my_extract", action_idx=0, action_config=config, is_last_action=False
            )

        assert captured_config["action_name"] == "my_extract"

    @pytest.mark.asyncio
    async def test_action_name_passed_to_handle_batch_agent_async(self, executor, mock_deps):
        """Async batch-check passes action_name through to handle_batch_agent."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.BATCH_SUBMITTED
        mock_deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")

        # action_name is pre-set by coordinator (not by executor)
        config = {"kind": "llm", "action_name": "my_extract"}

        with patch("agent_actions.workflow.executor.fire_event"):
            await executor.execute_action_async(
                "my_extract", action_idx=0, action_config=config, is_last_action=False
            )

        call_args = mock_deps.batch_manager.handle_batch_agent.call_args
        passed_config = call_args[0][2]
        assert passed_config["action_name"] == "my_extract"
