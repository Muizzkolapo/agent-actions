"""`agac retry` narrows only actions that finished their last run (1227).

A retry answers the records it names at every action from its starting point and carries
what each action already holds for the rest. That is sound for an action that finished:
what it holds for the rest is its answer. An action its last run left unfinished, reset
for an edit and stopped while running again or never run at all, holds nothing current
for the records that run had not reached, and the retry completed it on the ones it named.

Two tool actions over six staged records, `flatten` and `enrich`, which reads it. Every
command is a real `agac` invocation; only the fault that stops a run is stood in for,
raised where `enrich` marks a record answered.
"""

import json
from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.errors import ConfigurationError
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from tests.integration.test_an_upstream_edit_reruns_what_reads_it import _filter_the_first_page
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    SECOND_ACTION,
    TAG_TOOL,
    WORKFLOW,
    _disposition,
    _fail,
    _stored_guids,
    chained,  # noqa: F401
    project,  # noqa: F401
)

STOPS = pytest.mark.parametrize(
    ("stop", "left"),
    [
        pytest.param(KeyboardInterrupt(), "interrupted", id="interrupted"),
        pytest.param(ConfigurationError("the provider refused the key"), "failed", id="error"),
    ],
)


def _run(*args):
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])


def _retry(*args):
    return CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, *args])


def _status(project, action=SECOND):  # noqa: F811
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text()).get(action, {}).get("status", "pending")


@contextmanager
def _stopped_at_the_readers_third_record(stop):
    mark = SQLiteBackend.set_disposition
    answered = []

    def marking(self, action_name, record_id, disposition, *args, **kwargs):
        if action_name == SECOND and disposition == "success":
            answered.append(record_id)
            if len(answered) == 3:
                raise stop
        return mark(self, action_name, record_id, disposition, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(SQLiteBackend, "set_disposition", marking)
        yield


def _edit_then_stop_the_reader(project, stop):  # noqa: F811
    """The edit resets both actions; the run re-answers `flatten` and stops in `enrich`."""
    _filter_the_first_page(project)
    with _stopped_at_the_readers_third_record(stop):
        _run()
    assert len(_stored_guids(project, ACTION)) == RECORDS - 1
    assert len(_stored_guids(project, SECOND)) == RECORDS, "the reset deletes no row"


def _a_failure_at_the_first_action(project):  # noqa: F811
    named = _stored_guids(project, ACTION)[-1]
    _fail(project, named, ACTION)
    return named


@STOPS
def test_the_reader_ends_holding_what_the_edited_action_holds(chained, stop, left):  # noqa: F811
    """The sequence the issue measured: retry, then a plain run, after the stopped run."""
    _edit_then_stop_the_reader(chained, stop)
    assert _status(chained) == left
    named = _a_failure_at_the_first_action(chained)

    _retry("--record", named)
    result = _run()

    assert result.exit_code == 0, result.output
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


@STOPS
def test_the_retry_refuses_and_clears_nothing(chained, stop, left):  # noqa: F811
    _edit_then_stop_the_reader(chained, stop)
    named = _a_failure_at_the_first_action(chained)

    result = _retry("--record", named)

    assert result.exit_code != 0, result.output
    assert SECOND in result.output and "agac run" in result.output, result.output
    assert _status(chained) == left
    assert _disposition(chained, named, ACTION) == "failed"


def test_a_dry_run_says_the_retry_would_be_refused(chained):  # noqa: F811
    _edit_then_stop_the_reader(chained, KeyboardInterrupt())
    named = _a_failure_at_the_first_action(chained)

    result = _retry("--record", named, "--dry-run")

    assert result.exit_code == 0, result.output
    assert "would be refused" in result.output and SECOND in result.output, result.output
    assert _status(chained) == "interrupted"


def test_a_run_then_the_retry_repairs_the_record(chained):  # noqa: F811
    """The way out the refusal names."""
    _edit_then_stop_the_reader(chained, KeyboardInterrupt())
    named = _a_failure_at_the_first_action(chained)
    assert _retry("--record", named).exit_code != 0

    assert _run().exit_code == 0
    result = _retry("--record", named)

    assert result.exit_code == 0, result.output
    assert _disposition(chained, named, ACTION) == "success"
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


def test_a_retry_that_reaches_an_action_that_never_ran_refuses(project):  # noqa: F811
    """An action added since the last run owes every record, so completing it on the
    one record the retry named left the other five unanswered and the action complete."""
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
    (project / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)
    named = _a_failure_at_the_first_action(project)

    result = _retry("--record", named)

    assert result.exit_code != 0, result.output
    assert _status(project) == "pending"
    assert _run().exit_code == 0
    assert len(_stored_guids(project, SECOND)) == RECORDS
