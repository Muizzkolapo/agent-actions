"""Regression tests for the agent_* -> action_* rename bugs (P0 TypeErrors).

Each test targets a specific call-site that previously used the wrong parameter
names (action_config/action_name/action_configs instead of agent_config/agent_name/
agent_configs) or the wrong method name (run_agent instead of run_action).

If any of these renames are accidentally reverted, the corresponding test will fail.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.executor import (
    ActionExecutor,
    ActionRunParams,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager
from agent_actions.workflow.strategies import (
    InitialStrategy,
    StandardStrategy,
    StrategyExecutionParams,
)

# ── Bug 1: InitialStrategy.execute() must pass agent_config / agent_name ────


class TestInitialStrategyKwargs:
    """InitialStageContext must receive agent_config and agent_name, not action_*."""

    def test_initial_strategy_passes_agent_config_and_agent_name(self):
        """Verify InitialStageContext is constructed with agent_config / agent_name."""
        strategy = InitialStrategy(processor_factory=None)

        params = StrategyExecutionParams(
            action_config={"model_vendor": "openai"},
            action_name="my_action",
            file_path="/tmp/input.json",
            base_directory="/tmp/base",
            output_directory="/tmp/output",
            idx=0,
        )

        with (
            patch("agent_actions.workflow.strategies.process_initial_stage") as mock_process,
            patch("agent_actions.workflow.strategies.InitialStageContext") as mock_ctx_cls,
        ):
            mock_process.return_value = "/tmp/output/result.json"

            strategy.execute(params)

            # The InitialStageContext constructor must receive agent_config and agent_name as kwargs
            mock_ctx_cls.assert_called_once()
            call_kwargs = mock_ctx_cls.call_args.kwargs
            assert call_kwargs, "InitialStageContext must be called with keyword arguments"
            assert "agent_config" in call_kwargs, (
                "InitialStageContext should receive 'agent_config', not 'action_config'"
            )
            assert "agent_name" in call_kwargs, (
                "InitialStageContext should receive 'agent_name', not 'action_name'"
            )
            assert "action_config" not in call_kwargs
            assert "action_name" not in call_kwargs
            assert call_kwargs["agent_config"] == {"model_vendor": "openai"}
            assert call_kwargs["agent_name"] == "my_action"


# ── Bug 2: ActionStrategy._execute_generate_target() must pass agent_* kwargs ──


class TestActionStrategyPipelineKwargs:
    """create_processing_pipeline_from_params must receive agent_config, agent_name, agent_configs."""

    def test_execute_generate_target_passes_agent_kwargs(self):
        """Verify pipeline factory receives action_config, action_name, action_configs."""
        mock_factory = MagicMock()
        strategy = StandardStrategy(processor_factory=mock_factory)

        params = StrategyExecutionParams(
            action_config={"model_vendor": "openai"},
            action_name="my_action",
            file_path="/tmp/input.json",
            base_directory="/tmp/base",
            output_directory="/tmp/output",
            idx=1,
            action_configs={"my_action": {"model_vendor": "openai"}},
        )

        with patch(
            "agent_actions.workflow.pipeline.create_processing_pipeline_from_params"
        ) as mock_create:
            mock_pipeline = MagicMock()
            mock_pipeline.process.return_value = "/tmp/output/result.json"
            mock_create.return_value = mock_pipeline

            strategy.execute(params)

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs

            # Pipeline params now use action_* naming (unified in Wave 2)
            assert "action_config" in call_kwargs, "Should pass 'action_config' to pipeline factory"
            assert "action_name" in call_kwargs, "Should pass 'action_name' to pipeline factory"
            assert "action_configs" in call_kwargs, (
                "Should pass 'action_configs' to pipeline factory"
            )

            # Verify old agent_* kwarg names are not used
            assert "agent_config" not in call_kwargs
            assert "agent_name" not in call_kwargs
            assert "agent_configs" not in call_kwargs

            # Verify values are correct
            assert call_kwargs["action_config"] == {"model_vendor": "openai"}
            assert call_kwargs["action_name"] == "my_action"
            assert call_kwargs["action_configs"] == {"my_action": {"model_vendor": "openai"}}


# ── Bug 3: executor async_run must call run_action, not run_agent ───────────


class TestExecutorCallsRunAction:
    """Both sync and async executor paths must call action_runner.run_action."""

    @pytest.fixture
    def mock_deps(self):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock(spec=ActionStateManager)
        deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
        from agent_actions.workflow.runner import ActionRunner

        deps.action_runner = MagicMock(spec=ActionRunner)
        deps.skip_evaluator = MagicMock(spec=SkipEvaluator)
        deps.output_manager = MagicMock(spec=ActionOutputManager)
        deps.action_runner.workflow_name = "test_workflow"
        deps.action_runner.get_action_folder.return_value = "/tmp/agent_io"
        deps.action_runner.execution_order = ["agent_a"]
        return deps

    @pytest.fixture
    def executor(self, mock_deps):
        return ActionExecutor(mock_deps)

    def test_sync_run_calls_run_action(self, executor, mock_deps):
        """_execute_action_run must call action_runner.run_action, not run_agent."""
        mock_deps.action_runner.run_action.return_value = "/output"
        mock_deps.output_manager.setup_correlation_wrapper.return_value = None
        mock_deps.batch_manager.check_batch_submission.return_value = None

        params = ActionRunParams(
            action_name="agent_a",
            action_idx=0,
            action_config={"type": "llm"},
            is_last_action=True,
            start_time=__import__("datetime").datetime.now(),
        )

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor._execute_action_run(params)

        assert result.success is True
        mock_deps.action_runner.run_action.assert_called_once()
        # spec=ActionRunner means run_agent doesn't exist — accessing it would raise AttributeError
        assert not hasattr(mock_deps.action_runner, "run_agent")

    def test_async_run_calls_run_action(self, executor, mock_deps):
        """_execute_action_run_async must call action_runner.run_action, not run_agent."""
        mock_deps.action_runner.run_action.return_value = "/output"
        mock_deps.output_manager.setup_correlation_wrapper.return_value = None
        mock_deps.batch_manager.check_batch_submission.return_value = None

        params = ActionRunParams(
            action_name="agent_a",
            action_idx=0,
            action_config={"type": "llm"},
            is_last_action=True,
            start_time=__import__("datetime").datetime.now(),
        )

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = asyncio.run(executor._execute_action_run_async(params))

        assert result.success is True
        mock_deps.action_runner.run_action.assert_called()
        # spec=ActionRunner means run_agent doesn't exist — accessing it would raise AttributeError
        assert not hasattr(mock_deps.action_runner, "run_agent")
