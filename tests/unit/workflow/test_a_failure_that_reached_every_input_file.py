"""An action that failed after reaching every input file is marked as such.

`agac retry` narrows such an action like a completed one: every record it was
given holds its failure, so none the retry leaves out is lost. Any other failure
may have stopped the action partway, with records it never reached, and a retry
that narrowed it would complete it without them.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from agent_actions.errors import mark_action_fatal
from agent_actions.record.reasons import EVERY_INPUT_FAILED
from agent_actions.workflow.executor import ActionRunParams, action_failed_every_input
from agent_actions.workflow.runner_file_processing import CollectedErrors, _raise_all_files_failed
from tests.unit.workflow.test_halt_marker_reaches_every_producer import (
    ACTION,
    HALT_MARKER,
    _executor,
    _node_detail,
    _run_files_until_it_raises,
    backend,  # noqa: F401
    state_manager,  # noqa: F401
)


def _fail_with(executor, error):
    executor._handle_run_failure(
        ActionRunParams(
            action_name=ACTION,
            action_idx=0,
            action_config={"kind": "llm"},
            is_last_action=False,
            start_time=datetime.now(),
        ),
        error,
    )


def test_every_file_failing_on_its_own_is_marked(tmp_path, backend, state_manager):  # noqa: F811
    raised = _run_files_until_it_raises(tmp_path, ordinary=2, then_halt=False)

    _fail_with(_executor(backend, state_manager), raised)

    assert _node_detail(backend) == EVERY_INPUT_FAILED
    assert action_failed_every_input(backend, ACTION)


def test_a_halt_among_the_files_stays_a_halt(tmp_path, backend, state_manager):  # noqa: F811
    raised = _run_files_until_it_raises(tmp_path, ordinary=1, then_halt=True)

    _fail_with(_executor(backend, state_manager), raised)

    assert _node_detail(backend) == HALT_MARKER
    assert not action_failed_every_input(backend, ACTION)


def test_a_failure_fatal_to_the_action_is_not_marked(backend, state_manager):  # noqa: F811
    """It ends the file it came from partway, whatever the other files did."""
    errors = CollectedErrors()
    errors.record("a.json", RuntimeError("malformed record"))
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
