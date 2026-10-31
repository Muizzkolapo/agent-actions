"""What the startup reset keeps of an action stopped partway, as the next process finds it.

The executor records the config an action's work is answered under as it starts it. The
status file carries that to the next process, whose reset compares it with the config now
in force and names any edit; an edit resets nothing, and ``--rerun`` answers the action and
its readers again. Store, status file, executor and reset are real; the work is stood in for.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.storage.backend import (
    DISPOSITION_FAILED,
    DISPOSITION_SKIPPED,
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
    edits_since_its_work_began,
)
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from tests._support.logs import framework_records

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
    runner.staged_input_fingerprint.return_value = None
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


def _sequential(executor: ActionExecutor, params: ActionRunParams) -> None:
    executor._execute_action_run(params)


def _parallel(executor: ActionExecutor, params: ActionRunParams) -> None:
    asyncio.run(executor._execute_action_run_async(params))


def _stopped(
    tmp_path, backend, then: BaseException, *, retried=(), run=_sequential
) -> ActionStateManager:
    """A run starts define, finishes two records and fails a third, and is stopped."""
    state, executor = _process(tmp_path, backend, retried=retried)

    def work(*_args: Any, **_kwargs: Any) -> None:
        for guid, disposition in FINISHED.items():
            backend.set_disposition("define", guid, disposition)
        backend.set_disposition("define", "r3", DISPOSITION_FAILED)
        raise then

    executor.deps.action_runner.run_action.side_effect = work
    try:
        run(executor, ActionRunParams("define", 0, DEFINE, False, datetime.now()))
    except _Killed:
        pass
    return state


def _next_run_resets(
    tmp_path, backend, configs=CONFIGS, *, rerun: str | None = None
) -> ActionStateManager:
    """The next `agac run`'s startup reset, then what ``--rerun`` does after it."""
    state, executor = _process(tmp_path, backend, configs)
    workflow = object.__new__(AgentWorkflow)
    workflow.metadata = SimpleNamespace(action_configs=configs)
    workflow.storage_backend = backend
    workflow.services = SimpleNamespace(
        core=SimpleNamespace(state_manager=state, action_executor=executor)
    )
    workflow._reset_retryable_actions()
    if rerun is not None:
        executor.reopen_with_readers(rerun)
    return state


def _held(backend, action="define") -> dict[str, str]:
    return {row["record_id"]: row["disposition"] for row in backend.get_disposition(action)}


def _edited(**changes: Any) -> dict[str, Any]:
    return {**CONFIGS, "define": {**DEFINE, **changes}}


def _edit_warnings(records) -> list[str]:
    return [r.getMessage() for r in records if "was edited since" in r.getMessage()]


def _stopped_and_edited(label: str) -> str:
    return (
        f"define was edited since its last run started ({label}): the records it finished "
        "stand, a batch already sent is collected as it was sent, and the rest are answered "
        "under the edit. Run again with --rerun define to answer every record under the edit"
    )


PROMPT_EDIT = "action config (prompt/schema/guard)"


STOPS = pytest.mark.parametrize(
    "stop",
    [pytest.param(_Killed(), id="killed"), pytest.param(RuntimeError("timed out"), id="error")],
)
# `agac run` starts actions on the parallel path; each path records its own start.
RUNS = pytest.mark.parametrize(
    "run", [pytest.param(_sequential, id="sequential"), pytest.param(_parallel, id="parallel")]
)


@RUNS
@STOPS
def test_a_stopped_action_keeps_what_it_finished_while_its_config_is_unchanged(
    tmp_path, backend, stop, run
):
    _stopped(tmp_path, backend, stop, run=run)

    state = _next_run_resets(tmp_path, backend)

    assert _held(backend) == FINISHED
    assert state.get_status("define") == ActionStatus.PENDING


@STOPS
@pytest.mark.parametrize(
    ("edit", "label"),
    [
        ({"prompt": "Define it briefly"}, PROMPT_EDIT),
        ({"schema": "definition_v2"}, PROMPT_EDIT),
        ({"guard": "source.keep == true"}, PROMPT_EDIT),
        ({"model_name": "m2"}, "model"),
        ({"model_vendor": "v2"}, "model"),
    ],
    ids=["prompt", "schema", "guard", "model_name", "model_vendor"],
)
@RUNS
def test_a_stopped_action_edited_since_its_run_started_keeps_what_it_finished_and_names_the_edit(
    tmp_path, backend, stop, edit, label, run
):
    _stopped(tmp_path, backend, stop, run=run)

    with framework_records("agent_actions.workflow.coordinator") as records:
        state = _next_run_resets(tmp_path, backend, _edited(**edit))

    assert _held(backend) == FINISHED
    assert state.get_status("define") == ActionStatus.PENDING
    assert _edit_warnings(records) == [_stopped_and_edited(label)]


@STOPS
def test_rerun_of_a_stopped_edited_action_keeps_nothing(tmp_path, backend, stop):
    _stopped(tmp_path, backend, stop)

    state = _next_run_resets(tmp_path, backend, _edited(prompt="Define it briefly"), rerun="define")

    assert _held(backend) == {}
    assert state.get_status("define") == ActionStatus.PENDING


def test_what_reads_an_edited_stopped_action_keeps_its_answers_until_a_rerun(tmp_path, backend):
    """A reader can hold answers made from the stopped action's output: a retry or a
    node-level failure puts an action back to work and leaves its readers completed."""
    state, _ = _process(tmp_path, backend)
    state.update_status("grade", ActionStatus.COMPLETED)
    backend.set_disposition("grade", "r1", DISPOSITION_SUCCESS)
    _stopped(tmp_path, backend, _Killed())
    edited = _edited(prompt="Define it briefly")

    state = _next_run_resets(tmp_path, backend, edited)

    assert _held(backend, "grade") == {"r1": DISPOSITION_SUCCESS}
    assert state.get_status("grade") == ActionStatus.COMPLETED

    state = _next_run_resets(tmp_path, backend, edited, rerun="define")

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


def test_a_start_recorded_without_a_config_hash_is_reset_by_status_alone(tmp_path, backend):
    """A repair keeping a completion stamped before the digest existed records none, so
    nothing says what the records were answered under."""
    state, _ = _process(tmp_path, backend)
    state.update_status(
        "define",
        ActionStatus.FAILED,
        answered_under={"config_hash": None, "model_name": "m", "model_vendor": "v"},
    )
    for guid, disposition in FINISHED.items():
        backend.set_disposition("define", guid, disposition)

    _next_run_resets(tmp_path, backend)

    assert _held(backend) == {}


def test_a_skipped_action_is_cleared_whole_though_its_config_is_unchanged(tmp_path, backend):
    """A run that skips an action after starting it, finding no input file, answered
    nothing: what the action holds is not that run's work to carry."""
    _stopped(tmp_path, backend, _Killed())
    state, _ = _process(tmp_path, backend)
    state.update_status("define", ActionStatus.SKIPPED)
    backend.set_disposition("define", NODE_LEVEL_RECORD_ID, DISPOSITION_SKIPPED)

    _next_run_resets(tmp_path, backend)

    assert _held(backend) == {}


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

    details = ActionStateManager(tmp_path / ".agent_status.json", ORDER).get_status_details(
        "define"
    )
    assert edits_since_its_work_began(details, DEFINE) == []
    assert edits_since_its_work_began(details, edited["define"]) == [PROMPT_EDIT]

    with framework_records("agent_actions.workflow.coordinator") as records:
        _next_run_resets(tmp_path, backend, edited)

    assert _held(backend) == FINISHED
    assert _edit_warnings(records) == [_stopped_and_edited(PROMPT_EDIT)]


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

    details = ActionStateManager(tmp_path / ".agent_status.json", ORDER).get_status_details(
        "define"
    )
    assert edits_since_its_work_began(details, DEFINE) == []
    assert edits_since_its_work_began(details, edited["define"]) == [PROMPT_EDIT]

    with framework_records("agent_actions.workflow.coordinator") as records:
        _next_run_resets(tmp_path, backend, edited)

    assert _held(backend) == FINISHED
    assert _edit_warnings(records) == [_stopped_and_edited(PROMPT_EDIT)]


def test_an_edited_stopped_action_and_its_readers_keep_their_prompt_traces_until_a_rerun(
    tmp_path, backend
):
    """The answers stand, so the traces of the prompts that made them stand with them.
    ``--rerun`` asks every record again, and a trace of the run it replaces shows a
    prompt whose answer no longer stands."""
    state, _ = _process(tmp_path, backend)
    state.update_status("grade", ActionStatus.COMPLETED)
    for action in ORDER:
        backend.write_prompt_trace(action, "t1", "an old prompt", source_guid="r1")
    _stopped(tmp_path, backend, _Killed())
    edited = _edited(prompt="Define it briefly")

    _next_run_resets(tmp_path, backend, edited)

    assert [[t["source_guid"] for t in backend.get_prompt_traces(a)] for a in ORDER] == [
        ["r1"],
        ["r1"],
    ]

    _next_run_resets(tmp_path, backend, edited, rerun="define")

    assert [backend.get_prompt_traces(action) for action in ORDER] == [[], []]


def test_an_edited_stopped_action_that_keeps_answers_is_marked_as_kept(tmp_path, backend):
    _stopped(tmp_path, backend, _Killed())

    state = _next_run_resets(tmp_path, backend, _edited(prompt="Define it briefly"))

    assert "kept_answers_under" in state.get_status_details("define")


def test_an_action_cleared_in_bulk_drops_the_marker_of_answers_it_no_longer_holds(
    tmp_path, backend
):
    _stopped(tmp_path, backend, _Killed())
    state = _next_run_resets(tmp_path, backend, _edited(prompt="Define it briefly"))
    assert "kept_answers_under" in state.get_status_details("define")
    state.update_status("define", ActionStatus.SKIPPED)

    state = _next_run_resets(tmp_path, backend, _edited(prompt="Define it briefly"))

    assert _held(backend) == {}
    assert "kept_answers_under" not in state.get_status_details("define")


def test_an_action_cleared_in_bulk_drops_its_mixed_mark(tmp_path, backend):
    _stopped(tmp_path, backend, _Killed())
    state = _next_run_resets(tmp_path, backend)
    state.mark_mixed_answers(["define"])
    state.update_status("define", ActionStatus.SKIPPED)

    state = _next_run_resets(tmp_path, backend)

    assert "answers_under_more_than_one_config" not in state.get_status_details("define")
