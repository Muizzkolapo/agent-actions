"""Regression: parallel execution must not leak correlated input between actions.

Before the fix, _setup_correlation() monkey-patched runner.setup_directories
(shared mutable state).  When a version consumer and a non-consumer ran in the
same execution level, the non-consumer could see the patched wrapper and receive
the wrong input directories.

The fix passes correlated input as a parameter to run_action, making each
action's input resolution independent of other parallel tasks.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.executor import ActionExecutor, ActionRunParams


@pytest.fixture
def mock_deps():
    """Build executor dependencies with mocked output manager."""
    from agent_actions.workflow.executor import ExecutorDependencies

    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock()
    deps.action_runner = MagicMock()
    deps.output_manager = MagicMock()
    deps.batch_manager = MagicMock()
    deps.batch_manager.check_batch_submission.return_value = None
    deps.action_runner.run_action.return_value = "/output"
    deps.output_manager.execution_order = [
        "generate_optimal_code",
        "select_code_pattern",
        "generate_code_alternatives_1",
        "generate_code_alternatives_2",
        "merge_code_alternatives",
        "pick_code_pattern",
    ]
    return deps


@pytest.fixture
def executor(mock_deps):
    return ActionExecutor(mock_deps)


class TestParallelCorrelationIsolation:
    """Version-consumer correlation must not leak to non-consumers in the same level."""

    def test_non_consumer_gets_no_override(self, executor, mock_deps):
        """Non-version-consumer should receive input_directories_override=None."""
        mock_deps.output_manager.resolve_correlated_input.return_value = None

        params = ActionRunParams(
            action_name="pick_code_pattern",
            action_idx=5,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            executor._execute_action_run(params)

        mock_deps.action_runner.run_action.assert_called_once_with(
            params.action_config,
            "pick_code_pattern",
            None,
            5,
            input_directories_override=None,
        )

    def test_version_consumer_gets_correlated_dirs(self, executor, mock_deps):
        """Version consumer should receive correlated input directories."""
        correlated = ["/path/to/correlated"]
        mock_deps.output_manager.resolve_correlated_input.return_value = correlated

        params = ActionRunParams(
            action_name="merge_code_alternatives",
            action_idx=4,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            executor._execute_action_run(params)

        mock_deps.action_runner.run_action.assert_called_once_with(
            params.action_config,
            "merge_code_alternatives",
            None,
            4,
            input_directories_override=correlated,
        )

    def test_each_action_gets_its_own_override(self, executor, mock_deps):
        """Consumer and non-consumer executed sequentially get independent overrides."""

        def resolve_side_effect(idx):
            if idx == 4:  # merge_code_alternatives
                return ["/correlated"]
            return None  # pick_code_pattern

        mock_deps.output_manager.resolve_correlated_input.side_effect = resolve_side_effect

        consumer_params = ActionRunParams(
            action_name="merge_code_alternatives",
            action_idx=4,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )
        non_consumer_params = ActionRunParams(
            action_name="pick_code_pattern",
            action_idx=5,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            executor._execute_action_run(consumer_params)
            executor._execute_action_run(non_consumer_params)

        calls = mock_deps.action_runner.run_action.call_args_list
        assert calls[0].kwargs["input_directories_override"] == ["/correlated"]
        assert calls[1].kwargs["input_directories_override"] is None

    @pytest.mark.asyncio
    async def test_async_parallel_no_bleed(self, executor, mock_deps):
        """Async parallel execution: each task gets its own correlated input."""

        def resolve_side_effect(idx):
            if idx == 4:
                return ["/correlated"]
            return None

        mock_deps.output_manager.resolve_correlated_input.side_effect = resolve_side_effect

        consumer_params = ActionRunParams(
            action_name="merge_code_alternatives",
            action_idx=4,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )
        non_consumer_params = ActionRunParams(
            action_name="pick_code_pattern",
            action_idx=5,
            action_config={},
            is_last_action=False,
            start_time=datetime.now(),
        )

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            await asyncio.gather(
                executor._execute_action_run_async(consumer_params),
                executor._execute_action_run_async(non_consumer_params),
            )

        calls = mock_deps.action_runner.run_action.call_args_list
        overrides = [c.kwargs["input_directories_override"] for c in calls]

        # One call got correlated dirs, the other got None — regardless of order
        assert ["/correlated"] in overrides
        assert None in overrides
