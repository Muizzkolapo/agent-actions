"""What the startup reset keeps of an action stopped partway, as the next process finds it.

The executor records the config an action's work is answered under as it starts it. The
status file carries that to the next process, whose reset compares it with the config now
in force. Store, status file, executor and reset are real; the work is stood in for.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.storage.backend import (
    DISPOSITION_FAILED,
    DISPOSITION_SUCCESS,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.executor import (
    ActionExecutor,
    ActionRunParams,
    ExecutorDependencies,
    _compute_action_config_hash,
)
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ORDER = ["define", "grade"]
DEFINE = {"prompt": "Define it", "schema": "definition", "model_vendor": "v", "model_name": "m"}
CONFIGS = {"define": DEFINE, "grade": {"prompt": "Grade it", "dependencies": ["define"]}}
FINISHED = {"r1": DISPOSITION_SUCCESS, "r2": DISPOSITION_SUCCESS}


class _Killed(BaseException):
    """A hard kill: nothing unwinds, so the status stays what the run last wrote."""


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


def _process(tmp_path, backend, configs=CONFIGS, *, retried=()):
    """One `agac run`: a state manager read from the status file, and an executor."""
    state = ActionStateManager(tmp_path / ".agent_status.json", ORDER)
    runner = MagicMock()
    runner.storage_backend = backend
    runner.action_configs = configs
    runner.retried_records = frozenset(retried)
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


def _stopped(tmp_path, backend, then: BaseException, *, retried=()) -> ActionStateManager:
    """A run starts define, finishes two records and fails a third, and is stopped."""
    state, executor = _process(tmp_path, backend, retried=retried)

    def work(*_args: Any, **_kwargs: Any) -> None:
        for guid, disposition in FINISHED.items():
            backend.set_disposition("define", guid, disposition)
        backend.set_disposition("define", "r3", DISPOSITION_FAILED)
        raise then

    executor.deps.action_runner.run_action.side_effect = work
    try:
        executor._execute_action_run(ActionRunParams("define", 0, DEFINE, False, datetime.now()))
    except _Killed:
        pass
    return state


def _next_run_resets(tmp_path, backend, configs=CONFIGS) -> ActionStateManager:
    state, executor = _process(tmp_path, backend, configs)
    workflow = object.__new__(AgentWorkflow)
    workflow.metadata = SimpleNamespace(action_configs=configs)
    workflow.storage_backend = backend
    workflow.services = SimpleNamespace(
        core=SimpleNamespace(state_manager=state, action_executor=executor)
    )
    workflow._reset_retryable_actions()
    return state


def _held(backend, action="define") -> dict[str, str]:
    return {row["record_id"]: row["disposition"] for row in backend.get_disposition(action)}


def _edited(**changes: Any) -> dict[str, Any]:
    return {**CONFIGS, "define": {**DEFINE, **changes}}


STOPS = pytest.mark.parametrize(
    "stop",
    [pytest.param(_Killed(), id="killed"), pytest.param(RuntimeError("timed out"), id="error")],
)


@STOPS
def test_a_stopped_action_keeps_what_it_finished_while_its_config_is_unchanged(
    tmp_path, backend, stop
):
    _stopped(tmp_path, backend, stop)

    state = _next_run_resets(tmp_path, backend)

    assert _held(backend) == FINISHED
    assert state.get_status("define") == ActionStatus.PENDING


@STOPS
@pytest.mark.parametrize(
    "edit",
    [
        {"prompt": "Define it briefly"},
        {"schema": "definition_v2"},
        {"guard": "source.keep == true"},
        {"model_name": "m2"},
        {"model_vendor": "v2"},
    ],
    ids=lambda edit: next(iter(edit)),
)
def test_a_stopped_action_edited_since_its_run_started_keeps_nothing(tmp_path, backend, stop, edit):
    _stopped(tmp_path, backend, stop)

    state = _next_run_resets(tmp_path, backend, _edited(**edit))

    assert _held(backend) == {}
    assert state.get_status("define") == ActionStatus.PENDING


def test_what_reads_an_edited_action_is_reset_with_it(tmp_path, backend):
    """A reader can hold answers made from the stopped action's output: a retry or a
    node-level failure puts an action back to work and leaves its readers completed."""
    state, _ = _process(tmp_path, backend)
    state.update_status("grade", ActionStatus.COMPLETED)
    backend.set_disposition("grade", "r1", DISPOSITION_SUCCESS)
    _stopped(tmp_path, backend, _Killed())

    state = _next_run_resets(tmp_path, backend, _edited(prompt="Define it briefly"))

    assert _held(backend, "grade") == {}
    assert state.get_status("grade") == ActionStatus.PENDING


@pytest.mark.parametrize(
    ("status", "kept"),
    [(ActionStatus.INTERRUPTED, FINISHED), (ActionStatus.FAILED, {})],
)
def test_a_status_written_before_the_start_was_recorded_is_reset_by_status_alone(
    tmp_path, backend, status, kept
):
    """Nothing says what such an action's records were answered under, so the reset
    does what it did before it could tell: keep an interrupted one, wipe a failed one."""
    state, _ = _process(tmp_path, backend)
    state.update_status("define", status)
    for guid, disposition in FINISHED.items():
        backend.set_disposition("define", guid, disposition)

    _next_run_resets(tmp_path, backend, _edited(prompt="Define it briefly"))

    assert _held(backend) == kept


def test_an_action_halted_on_purpose_is_left_alone_though_it_was_edited(tmp_path, backend):
    halt = AgentActionsError("exhausted", context={"on_exhausted": "raise"})
    _stopped(tmp_path, backend, halt)

    state = _next_run_resets(tmp_path, backend, _edited(prompt="Define it briefly"))

    assert state.get_status("define") == ActionStatus.FAILED
    assert NODE_LEVEL_RECORD_ID in _held(backend)


def test_a_repair_records_the_config_of_the_completion_it_keeps(tmp_path, backend):
    """A retry answers the records it names under the edit and leaves the rest as the
    old config answered them. Stopped partway, the next run must still see the edit."""
    state, _ = _process(tmp_path, backend)
    state.update_status(
        "define",
        ActionStatus.COMPLETED,
        config_hash=_compute_action_config_hash(DEFINE),
        model_name="m",
        model_vendor="v",
    )
    state.update_status("define", ActionStatus.PENDING)
    edited = _edited(prompt="Define it briefly")
    state, executor = _process(tmp_path, backend, edited, retried={"r3"})
    executor.deps.action_runner.run_action.side_effect = _Killed()
    with pytest.raises(_Killed):
        executor._execute_action_run(
            ActionRunParams("define", 0, edited["define"], False, datetime.now())
        )
    for guid, disposition in FINISHED.items():
        backend.set_disposition("define", guid, disposition)

    _next_run_resets(tmp_path, backend, edited)

    assert _held(backend) == {}


def test_a_repair_of_an_action_that_never_completed_records_what_its_last_run_started_under(
    tmp_path, backend
):
    """No completion stamp says what the records a retry does not name were answered
    under; the start the stopped run recorded does, and the edit is the next run's."""
    _stopped(tmp_path, backend, _Killed())
    edited = _edited(prompt="Define it briefly")
    state, executor = _process(tmp_path, backend, edited, retried={"r3"})
    executor.deps.action_runner.run_action.side_effect = _Killed()
    with pytest.raises(_Killed):
        executor._execute_action_run(
            ActionRunParams("define", 0, edited["define"], False, datetime.now())
        )

    _next_run_resets(tmp_path, backend, edited)

    assert _held(backend) == {}
