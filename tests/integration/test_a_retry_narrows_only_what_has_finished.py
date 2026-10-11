"""`agac retry` narrows only actions that finished their last run (1227).

A retry answers the records it names at every action it runs and carries what each
action already holds for the rest. That is sound for an action that finished: what it
holds for the rest is its answer. An action its last run left unfinished, reset for an
edit and stopped while running again or never run at all, holds nothing current for the
records that run had not reached, and the retry completed it on the ones it named.

Two tool actions over six staged records, `flatten` and `enrich`, which reads it. Every
command is a real `agac` invocation; only the faults are stood in for: the one that stops
a run, raised where an action marks a record answered, and tools that fail.
"""

import json
from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.errors import ConfigurationError
from agent_actions.errors.operations import TemplateVariableError
from agent_actions.llm.providers.tools import client as tool_client
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.runner import ActionRunner
from tests.integration.test_an_upstream_edit_reruns_what_reads_it import _filter_the_first_page
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    SECOND_ACTION,
    TAG_TOOL,
    WORKFLOW,
    _backend,
    _disposition,
    _fail,
    _record_ids,
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
def _stopped_at_the_readers_record(stop, nth=3, action=SECOND):
    mark = SQLiteBackend.set_disposition
    answered = []

    def marking(self, action_name, record_id, disposition, *args, **kwargs):
        if action_name == action and disposition == "success":
            answered.append(record_id)
            if len(answered) == nth:
                raise stop
        return mark(self, action_name, record_id, disposition, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(SQLiteBackend, "set_disposition", marking)
        yield


def _edit_then_stop_the_reader(project, stop):  # noqa: F811
    """The edit resets both actions; the run re-answers `flatten` and stops in `enrich`."""
    _filter_the_first_page(project)
    with _stopped_at_the_readers_record(stop):
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


def test_a_retry_stopped_partway_is_resumed_by_retrying_again(chained):  # noqa: F811
    """What the stopped retry left unfinished had finished before it, and owes only the
    records that retry named."""
    named = _a_failure_at_the_first_action(chained)
    with _stopped_at_the_readers_record(KeyboardInterrupt(), nth=1):
        _retry("--record", named)
    assert _status(chained) == "interrupted"

    result = _retry("--record", named)

    assert result.exit_code == 0, result.output
    assert _disposition(chained, named, SECOND) == "success"
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


@contextmanager
def _the_first_action_fails_every_record():
    run_tool = tool_client.execute_user_defined_function

    def flatten_fails(udf_name, *args, **kwargs):
        if udf_name == "flatten_pages":
            raise RuntimeError("the tool blew up")
        return run_tool(udf_name, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(tool_client, "execute_user_defined_function", flatten_fails)
        yield


def test_a_retry_after_an_action_failed_every_record_still_runs(chained):  # noqa: F811
    """Every record holds its failure there, so none the retry leaves out is lost."""
    with _the_first_action_fails_every_record():
        _run("--fresh")
    assert (_status(chained, ACTION), _status(chained)) == ("failed", "skipped")
    named = _record_ids(chained, ACTION)[0]

    result = _retry("--record", named)

    assert result.exit_code == 0, result.output
    assert _disposition(chained, named, ACTION) == "success"
    assert _disposition(chained, named, SECOND) == "success"


def test_a_retry_whose_record_failed_again_can_be_retried_again(chained):  # noqa: F811
    """The record it named failing again fails the action, which reached all it was given."""
    named = _a_failure_at_the_first_action(chained)
    with _the_first_action_fails_every_record():
        _retry("--record", named)
    assert _status(chained, ACTION) == "failed"

    result = _retry("--record", named)

    assert result.exit_code == 0, result.output
    assert _disposition(chained, named, SECOND) == "success"
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


AUDIT_ACTION = """  - name: audit
    kind: tool
    dependencies: [flatten]
    intent: "Audit"
    schema: tool_action_output
    impl: tag_density
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


@pytest.mark.parametrize("left", ["pending", "interrupted"])
def test_an_unfinished_action_ordered_before_the_starting_point_refuses(chained, left):  # noqa: F811
    """`audit` reads `flatten` beside `enrich`. Declared after it, it runs before it, so a
    retry starting at `enrich` still runs it: added since the last run, or stopped partway."""
    named = _stored_guids(chained, SECOND)[-1]
    _fail(chained, named, SECOND)
    config = chained / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + AUDIT_ACTION)
    if left == "interrupted":
        with _stopped_at_the_readers_record(KeyboardInterrupt(), action="audit"):
            _run()
    assert _status(chained, "audit") == left

    result = _retry()

    assert result.exit_code != 0, result.output
    assert f"audit ({left})" in result.output, result.output
    assert _run().exit_code == 0
    assert len(_stored_guids(chained, "audit")) == RECORDS


@contextmanager
def _the_readers_tool_raises(error, from_call=1):
    run_tool = tool_client.execute_user_defined_function
    calls = []

    def raising(udf_name, *args, **kwargs):
        if udf_name == "tag_density":
            calls.append(udf_name)
            if len(calls) >= from_call:
                raise error
        return run_tool(udf_name, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(tool_client, "execute_user_defined_function", raising)
        yield


def test_a_reader_an_error_stopped_partway_on_its_first_run_refuses(chained):  # noqa: F811
    """A render failure one record's data provoked, which the record loop re-raises and no
    one declares fatal, ends its file at that record: two answered, three never reached.
    Taken as a failure on every record, the retry completed it on the one it named.

    Raised from the reader's tool, it stands in for that failure in an LLM reader's
    prompt: a tool's own error fails only its record, and a tool renders no prompt."""
    stops = TemplateVariableError(
        missing_variables=[],
        available_variables=["flatten"],
        agent_name=SECOND,
        mode="online",
        cause=TypeError("unsupported operand type(s) for +: 'int' and 'dict'"),
    )
    with _the_readers_tool_raises(stops, from_call=3):
        _run("--fresh")
    assert (_status(chained, ACTION), _status(chained)) == ("completed", "failed")
    named = _a_failure_at_the_first_action(chained)

    result = _retry("--record", named)

    assert result.exit_code != 0, result.output
    assert "enrich (failed)" in result.output, result.output
    assert _run().exit_code == 0
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


@contextmanager
def _every_file_of_the_reader_fails():
    process = ActionRunner._process_single_file

    def failing(self, params, *args, **kwargs):
        if params.action_name == SECOND:
            raise OSError("the disk was full")
        return process(self, params, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(ActionRunner, "_process_single_file", failing)
        yield


@pytest.mark.parametrize(
    "fault",
    [pytest.param(_every_file_of_the_reader_fails, id="every_file")],
)
def test_a_reader_that_failed_everything_after_a_reset_refuses(chained, fault):  # noqa: F811
    """The reset deletes no row, and a run whose every file fails before it is processed
    writes none, so the reader still holds the row of the page its source now filters.
    Nothing would reach that row again once a retry carried it."""
    _filter_the_first_page(chained)
    with fault():
        _run()
    assert _status(chained) == "failed"
    named = _a_failure_at_the_first_action(chained)

    result = _retry("--record", named)

    assert result.exit_code != 0, result.output
    assert "enrich (failed)" in result.output, result.output
    assert _run().exit_code == 0
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


def test_a_reader_whose_every_record_failed_after_a_reset_is_narrowed(chained):  # noqa: F811
    """A file in which every record fails after a reset is written with its failures
    (1283), so the reader keeps no row of the page its source now filters, only a failure
    for each record it reached. That failure reached all of its input, which is what a
    retry is for, so the retry narrows it."""
    _filter_the_first_page(chained)
    with _the_readers_tool_raises(RuntimeError("blew up")):
        _run()
    assert _status(chained) == "failed"
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)
    named = _a_failure_at_the_first_action(chained)

    result = _retry("--record", named)

    assert result.exit_code == 0, result.output
    assert _disposition(chained, named, SECOND) == "success"
    assert _run().exit_code == 0
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


def test_a_stale_manifest_does_not_lift_the_refusal(chained):  # noqa: F811
    """Only a retry reads or deletes the manifest of one that was interrupted, so it
    outlives the plain runs after it. Those runs reset and stop `enrich` on their own."""
    named = _a_failure_at_the_first_action(chained)
    with _stopped_at_the_readers_record(KeyboardInterrupt(), nth=1):
        _retry("--record", named)
    assert _run().exit_code == 0
    _edit_then_stop_the_reader(chained, KeyboardInterrupt())
    named = _a_failure_at_the_first_action(chained)

    result = _retry("--record", named)

    assert result.exit_code != 0, result.output
    assert "enrich (interrupted)" in result.output, result.output
    assert _run().exit_code == 0
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


def test_a_completed_action_whose_output_is_gone_refuses(chained):  # noqa: F811
    """A plain run answers everything again for it; narrowed, it completed on one row."""
    backend = _backend(chained)
    try:
        backend.delete_target(SECOND)
    finally:
        backend.close()
    named = _a_failure_at_the_first_action(chained)

    result = _retry("--record", named)

    assert result.exit_code != 0, result.output
    assert "enrich (its output is gone)" in _unwrapped(result.output), result.output
    assert _run().exit_code == 0
    assert len(_stored_guids(chained, SECOND)) == RECORDS


def _unwrapped(output):
    return " ".join(output.split())
