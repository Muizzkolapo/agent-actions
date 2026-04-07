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

    def test_run_tracker_and_run_id_are_attributes(self, executor):
        """Attributes must exist — no AttributeError on access."""
        assert executor.run_tracker is None
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

    def test_track_action_start_invokes_record_when_tracker_set(self, executor):
        """Setting run_tracker/run_id and calling _track_action_start must invoke record_action_start."""
        mock_tracker = MagicMock()
        executor.run_tracker = mock_tracker
        executor.run_id = "run-abc-123"

        params = ActionRunParams(
            action_name="enrich_data",
            action_idx=1,
            action_config={"model_vendor": "openai", "model_name": "gpt-4"},
            is_last_action=False,
            start_time=datetime.now(),
        )
        executor._track_action_start(params)

        mock_tracker.record_action_start.assert_called_once_with(
            run_id="run-abc-123",
            action_name="enrich_data",
            action_type="llm",
            action_config=params.action_config,
        )

    def test_track_action_start_tool_type(self, executor):
        """Action with model_vendor='tool' must record action_type='tool'."""
        mock_tracker = MagicMock()
        executor.run_tracker = mock_tracker
        executor.run_id = "run-xyz"

        params = ActionRunParams(
            action_name="my_tool",
            action_idx=0,
            action_config={"model_vendor": "tool"},
            is_last_action=True,
            start_time=datetime.now(),
        )
        executor._track_action_start(params)

        call_kwargs = mock_tracker.record_action_start.call_args.kwargs
        assert call_kwargs["action_type"] == "tool"

    def test_track_action_start_hitl_type(self, executor):
        """Action with model_vendor='hitl' must record action_type='hitl'."""
        mock_tracker = MagicMock()
        executor.run_tracker = mock_tracker
        executor.run_id = "run-hitl"

        params = ActionRunParams(
            action_name="human_review",
            action_idx=2,
            action_config={"model_vendor": "hitl"},
            is_last_action=False,
            start_time=datetime.now(),
        )
        executor._track_action_start(params)

        call_kwargs = mock_tracker.record_action_start.call_args.kwargs
        assert call_kwargs["action_type"] == "hitl"
