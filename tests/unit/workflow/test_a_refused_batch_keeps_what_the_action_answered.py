"""An action a refused batch failed, as the next process finds it.

The refusal sent and stored nothing, so the records the action had answered before it
are still answered. The status file is all that crosses to the run that resets the
action, and the dispositions are what that reset decides. Store, status file, executor
and reset are real; the file walk is stood in for.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import DependencyError, ExternalServiceError, mark_action_fatal
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_FAILED,
    DISPOSITION_SUCCESS,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.executor import ActionExecutor, ActionRunParams, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "agent_a"
CONFIG = {"prompt": "Answer it", "model_vendor": "openai", "model_name": "m"}


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    # One file answered by an earlier batch, one still at the provider, one record failed.
    store.set_disposition(ACTION, "answered", DISPOSITION_SUCCESS)
    store.set_disposition(ACTION, "waiting", DISPOSITION_DEFERRED)
    store.set_disposition(ACTION, "broken", DISPOSITION_FAILED)
    yield store
    store.close()


def _refused() -> DependencyError:
    """What the file walk raises once the provider has refused one file's batch."""
    refusal = mark_action_fatal(ExternalServiceError("Failed to submit batch job: quota exceeded"))
    return DependencyError(
        f"Action '{ACTION}': a.json: {refusal} (Processed 1 of 2 files.)", cause=refusal
    )


def _process(tmp_path, backend, config: dict[str, Any]):
    """One `agac run`: a state manager read from the status file, and an executor."""
    state = ActionStateManager(tmp_path / ".agent_status.json", [ACTION])
    runner = MagicMock()
    runner.storage_backend = backend
    runner.action_configs = {ACTION: config}
    runner.retried_records = frozenset()
    output = MagicMock()
    output.resolve_correlated_input.return_value = None
    executor = ActionExecutor(
        ExecutorDependencies(
            action_runner=runner,
            state_manager=state,
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=output,
        )
    )
    return state, executor


def _failed(tmp_path, backend, error: Exception) -> None:
    """The run that failed: started by the executor, which records its config, then raised."""
    _state, executor = _process(tmp_path, backend, CONFIG)
    executor.deps.action_runner.run_action.side_effect = error
    executor._execute_action_run(ActionRunParams(ACTION, 0, CONFIG, False, datetime.now()))


def _next_run_resets(tmp_path, backend, config=CONFIG) -> ActionStateManager:
    """The next process, under *config*: the reset it runs first."""
    state, executor = _process(tmp_path, backend, config)
    workflow = object.__new__(AgentWorkflow)
    workflow.metadata = SimpleNamespace(action_configs={ACTION: config})
    workflow.storage_backend = backend
    workflow.services = SimpleNamespace(
        core=SimpleNamespace(state_manager=state, action_executor=executor)
    )
    workflow._reset_retryable_actions()
    return state


def _dispositions(backend) -> dict[str, str]:
    return {row["record_id"]: row["disposition"] for row in backend.get_disposition(ACTION)}


def test_the_records_it_had_answered_are_still_done_for_the_next_run(tmp_path, backend):
    _failed(tmp_path, backend, _refused())

    manager = _next_run_resets(tmp_path, backend)

    assert _dispositions(backend) == {"answered": DISPOSITION_SUCCESS}
    assert manager.get_status(ACTION) == ActionStatus.PENDING


def test_an_edit_since_the_refusal_answers_every_record_again(tmp_path, backend):
    """The refusal stored nothing, but what came before it was answered under the old prompt."""
    _failed(tmp_path, backend, _refused())

    _next_run_resets(tmp_path, backend, {**CONFIG, "prompt": "Answer it again"})

    assert _dispositions(backend) == {}
