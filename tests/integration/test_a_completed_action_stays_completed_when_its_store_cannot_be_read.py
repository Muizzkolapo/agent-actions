"""A completed action stays completed when its stored output cannot be read (1229).

Before skipping a completed action, a run checks that it still holds its output. When
that read failed, the action was run again. It still held its rows and its records'
dispositions, so it carried them and answered again the record it had failed, which a
plain run of a completed action never does. That record now succeeded and the action
gained a row, while the action reading it stayed completed, holding the record as one
its upstream never answered: neither `agac run` nor `agac retry` reached it again.

Two tool actions over six staged records, `flatten` and `enrich`, which reads it. Every
command is a real `agac` invocation; only the faults are stood in for: a tool that fails
on one record, and one read of the store that fails.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.llm.providers.tools import client as tool_client
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    SECOND,
    WORKFLOW,
    _disposition,
    _record_ids,
    chained,  # noqa: F401
    project,  # noqa: F401
)

FAILING_PAGE = "page 3"


def _run(*args):
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])


def _status(project, action):  # noqa: F811
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[action]["status"]


@contextmanager
def _flatten_fails_on_one_page():
    run_tool = tool_client.execute_user_defined_function

    def failing(udf_name, input_data, *args, **kwargs):
        if udf_name == "flatten_pages" and FAILING_PAGE in json.dumps(input_data, default=str):
            raise RuntimeError("the tool blew up")
        return run_tool(udf_name, input_data, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(tool_client, "execute_user_defined_function", failing)
        yield


@contextmanager
def _the_first_read_of_flattens_output_fails():
    listed = SQLiteBackend.list_target_files
    failed = []

    def unreadable_once(self, action_name):
        if action_name == ACTION and not failed:
            failed.append(action_name)
            raise sqlite3.OperationalError("disk I/O error")
        return listed(self, action_name)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(SQLiteBackend, "list_target_files", unreadable_once)
        yield
    assert failed, "the store was never read for flatten's output"


@contextmanager
def _executor_warnings():
    """Read at the executor's own logger: a run stops `agent_actions` logging from
    propagating to the root logger, where caplog listens."""
    warnings = []

    class Collecting(logging.Handler):
        def emit(self, record):
            warnings.append(record.getMessage())

    executor_log = logging.getLogger("agent_actions.workflow.executor")
    handler = Collecting(logging.WARNING)
    executor_log.addHandler(handler)
    try:
        yield warnings
    finally:
        executor_log.removeHandler(handler)


@pytest.fixture
def one_record_failed(chained):  # noqa: F811
    """`flatten` completed with one failure, `enrich` completed without that record."""
    with _flatten_fails_on_one_page():
        assert _run("--fresh").exit_code == 0
    assert (_status(chained, ACTION), _status(chained, SECOND)) == (
        "completed_with_failures",
        "completed",
    )
    (failed,) = [guid for guid in _record_ids(chained) if _disposition(chained, guid) == "failed"]
    assert _disposition(chained, failed, SECOND) == "unprocessed"
    return chained, failed


def test_a_plain_run_leaves_the_failed_record_to_retry(one_record_failed):
    """The warning says the failed read was the one verifying `flatten`, not a read the
    run made anywhere else."""
    root, failed = one_record_failed

    with _the_first_read_of_flattens_output_fails(), _executor_warnings() as warnings:
        result = _run()

    assert result.exit_code == 0, result.output
    verifying = f"Could not read whether {ACTION} still holds its output"
    assert any(verifying in w for w in warnings), warnings
    assert _status(root, ACTION) == "completed_with_failures"
    assert _disposition(root, failed) == "failed"
    assert _disposition(root, failed, SECOND) == "unprocessed"


def test_retry_then_answers_the_record_at_every_action(one_record_failed):
    """The way back for a failed record. The run that answered it on a failed read left
    `enrich` holding it as unanswered upstream, which retry does not look for."""
    root, failed = one_record_failed
    with _the_first_read_of_flattens_output_fails():
        _run()

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert _disposition(root, failed) == "success"
    assert _disposition(root, failed, SECOND) == "success"
