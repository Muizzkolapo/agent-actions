"""Wave 12 T1-4 regression: ActionExecutor run_tracker/run_id init and hasattr removal."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from agent_actions.workflow.executor import (
    ActionExecutor,
    ActionRunParams,
    ExecutorDependencies,
)


@pytest.fixture
def mock_deps():
    deps = MagicMock(spec=ExecutorDependencies)
    deps.action_runner = MagicMock()
    deps.action_runner.staged_input_fingerprint.return_value = None
    deps.state_manager = MagicMock()
    deps.skip_evaluator = MagicMock()
    deps.batch_manager = MagicMock()
    deps.output_manager = MagicMock()
    return deps


@pytest.fixture
def executor(mock_deps):
    return ActionExecutor(mock_deps)


class TestExecutorRunTrackerInit:
    """T1-4: run_tracker and run_id must be initialised to None in __init__."""

    def test_run_tracker_is_none_by_default(self, executor):
        assert executor.run_tracker is None

    def test_run_id_is_none_by_default(self, executor):
        assert executor.run_id is None

    def test_track_action_start_noop_when_tracker_is_none(self, executor):
        """_track_action_start must be a no-op when run_tracker is None."""
        params = ActionRunParams(
            action_name="test_action",
            action_idx=0,
            action_config={"model_vendor": "openai", "model_name": "gpt-4"},
            is_last_action=False,
            start_time=datetime.now(),
        )
        assert executor.run_tracker is None
        result = executor._track_action_start(params)
        assert result is None

    @pytest.mark.parametrize(
        ("action_config", "action_type"),
        [
            pytest.param({"model_vendor": "openai", "model_name": "gpt-4"}, "llm", id="llm"),
            pytest.param({"model_vendor": "tool"}, "tool", id="tool"),
            pytest.param({"model_vendor": "hitl"}, "hitl", id="hitl"),
        ],
    )
    def test_track_action_start_records_the_action_type(self, executor, action_config, action_type):
        mock_tracker = MagicMock()
        executor.run_tracker = mock_tracker
        executor.run_id = "run-abc-123"

        params = ActionRunParams(
            action_name="enrich_data",
            action_idx=1,
            action_config=action_config,
            is_last_action=False,
            start_time=datetime.now(),
        )
        executor._track_action_start(params)

        mock_tracker.record_action_start.assert_called_once_with(
            run_id="run-abc-123",
            action_name="enrich_data",
            action_type=action_type,
            action_config=action_config,
        )
