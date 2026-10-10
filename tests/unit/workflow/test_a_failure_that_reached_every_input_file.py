"""An action that failed after reaching every record of its input is marked as such.

`agac retry` narrows such an action like a completed one: every record it was
given holds its failure, so none the retry leaves out is lost. Any other failure
may have stopped the action partway, with records it never reached, and a retry
that narrowed it would complete it without them.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import SchemaValidationError, mark_action_fatal
from agent_actions.processing.result_collector import CollectionStats
from agent_actions.record.reasons import EVERY_INPUT_FAILED
from agent_actions.workflow.executor import ActionRunParams, action_failed_every_input
from agent_actions.workflow.managers.state import ActionStatus
from agent_actions.workflow.runner import ActionRunner, FileProcessParams
from agent_actions.workflow.runner_file_processing import (
    _MAX_TRACKED_ERRORS,
    CollectedErrors,
    _raise_all_files_failed,
    process_files,
)
from tests.unit.workflow.test_halt_marker_reaches_every_producer import (
    ACTION,
    HALT_MARKER,
    _executor,
    _node_detail,
    _run_files_until_it_raises,
    _write,
    backend,  # noqa: F401
    state_manager,  # noqa: F401
)


def _params() -> ActionRunParams:
    return ActionRunParams(
        action_name=ACTION,
        action_idx=0,
        action_config={"kind": "llm"},
        is_last_action=False,
        start_time=datetime.now(),
    )


def _fail_with(executor, error):
    executor._handle_run_failure(_params(), error)


def _every_record_failed() -> Exception:
    """What a file raises when every one of its records failed: the collector's own error."""
    with pytest.raises(RuntimeError) as raised:
        CollectionStats(failed=2).raise_if_terminal_failure(ACTION, [{}, {}], [])
    return raised.value


def _stopped_partway() -> Exception:
    """A UDF output that fails validation is re-raised from the record loop, ending its file."""
    return SchemaValidationError("output did not validate")


def _walk(tmp_path, outcomes: list[Exception | None]) -> tuple[ActionRunner, Exception | None]:
    """Drive the real process_files over one file per outcome: the error it raises, or None."""
    source = tmp_path / "input"
    for i in range(len(outcomes)):
        _write(source / f"f{i:03d}.json")
    strategy = MagicMock()
    seen: list[str] = []

    def execute(exec_params):
        seen.append(exec_params.file_path)
        outcome = outcomes[len(seen) - 1]
        if outcome is not None:
            raise outcome

    strategy.execute.side_effect = execute
    runner = ActionRunner(use_tools=True)
    params = FileProcessParams(
        action_config={"agent_type": "test"},
        action_name=ACTION,
        strategy=strategy,
        upstream_data_dirs=[str(source)],
        output_directory=str(tmp_path / "out"),
        idx=0,
    )
    try:
        process_files(runner, params)
    except Exception as error:
        return runner, error
    return runner, None


def test_every_file_failing_on_every_record_is_marked(tmp_path, backend, state_manager):  # noqa: F811
    _runner, raised = _walk(tmp_path, [_every_record_failed(), _every_record_failed()])

    _fail_with(_executor(backend, state_manager), raised)

    assert _node_detail(backend) == EVERY_INPUT_FAILED
    assert action_failed_every_input(backend, ACTION)


def test_a_file_stopped_partway_is_not_marked(tmp_path, backend, state_manager):  # noqa: F811
    """The records past where it stopped hold nothing, whatever the other files did."""
    _runner, raised = _walk(tmp_path, [_every_record_failed(), _stopped_partway()])

    _fail_with(_executor(backend, state_manager), raised)

    assert _node_detail(backend) is None
    assert not action_failed_every_input(backend, ACTION)


def test_a_file_stopped_partway_counts_past_the_tracked_error_cap(
    tmp_path,
    backend,  # noqa: F811
    state_manager,  # noqa: F811
):
    outcomes = [_every_record_failed()] * (_MAX_TRACKED_ERRORS + 1) + [_stopped_partway()]
    _runner, raised = _walk(tmp_path, outcomes)

    _fail_with(_executor(backend, state_manager), raised)

    assert _node_detail(backend) is None


def test_a_file_lost_without_being_read_is_not_marked(backend, state_manager):  # noqa: F811
    """A directory or entry the walk could not open reached none of its records."""
    errors = CollectedErrors()
    errors.record("a.json", _every_record_failed())
    errors.record("sub", PermissionError("cannot list"))
    with pytest.raises(Exception) as raised:  # noqa: PT011 - the type is not the subject
        _raise_all_files_failed(ACTION, 2, [], errors)

    _fail_with(_executor(backend, state_manager), raised.value)

    assert _node_detail(backend) is None


def test_a_halt_among_the_files_stays_a_halt(tmp_path, backend, state_manager):  # noqa: F811
    raised = _run_files_until_it_raises(tmp_path, ordinary=1, then_halt=True)

    _fail_with(_executor(backend, state_manager), raised)

    assert _node_detail(backend) == HALT_MARKER
    assert not action_failed_every_input(backend, ACTION)


def test_a_failure_fatal_to_the_action_is_not_marked(backend, state_manager):  # noqa: F811
    """It ends the file it came from partway, whatever the other files did."""
    errors = CollectedErrors()
    errors.record("a.json", _every_record_failed())
    errors.record("b.json", mark_action_fatal(RuntimeError("the provider refused the key")))
    with pytest.raises(Exception) as raised:  # noqa: PT011 - the type is not the subject
        _raise_all_files_failed(ACTION, 2, [], errors)

    _fail_with(_executor(backend, state_manager), raised.value)

    assert _node_detail(backend) is None
    assert not action_failed_every_input(backend, ACTION)


def test_an_error_from_outside_the_file_pass_is_not_marked(backend, state_manager):  # noqa: F811
    _fail_with(_executor(backend, state_manager), OSError("the output folder could not be made"))

    assert _node_detail(backend) is None
    assert not action_failed_every_input(backend, ACTION)


@pytest.mark.parametrize(
    ("lost", "marked"),
    [
        pytest.param(_every_record_failed(), EVERY_INPUT_FAILED, id="lost_whole"),
        pytest.param(_stopped_partway(), None, id="lost_partway"),
    ],
)
def test_a_pass_that_processed_a_file_is_marked_by_how_it_lost_the_others(
    tmp_path,
    backend,  # noqa: F811
    state_manager,  # noqa: F811
    lost,
    marked,
):
    """One file answered nothing (every record filtered) and so did not raise, so the pass
    ends normally and the failure is read from the records, every one of which failed.
    Whether that is all of its input depends on how the other file was lost."""
    runner, raised = _walk(tmp_path, [None, lost])
    assert raised is None
    backend.set_disposition(ACTION, "r1", "failed", reason="the provider refused")
    executor = _executor(backend, state_manager)
    runner.storage_backend = backend
    executor.deps.action_runner = runner

    executor._handle_run_success(_params(), str(tmp_path / "out"), 0.0, None, 0)

    assert state_manager.get_status(ACTION) == ActionStatus.FAILED
    assert _node_detail(backend) == marked
