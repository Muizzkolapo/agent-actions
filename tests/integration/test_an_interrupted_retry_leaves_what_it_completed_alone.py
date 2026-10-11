"""A retry after an interrupted one puts its failures back only where they still hold (1268).

A retry snapshots the failures it is about to clear, and a retry after one that was
interrupted puts them back, so it starts where that one did. `--dry-run` put them back
too, and deleted the snapshot, though it says it changes nothing. And they went back on
every action, an action the interrupted retry completed included: a node-level failure
there makes the next plain run answer every record of it again, while what its readers
built from the rows it replaces stands.

Two tool actions over six staged records, `flatten` and `enrich`, which reads it. Every
command is a real `agac` invocation; only the faults are stood in for: a tool that fails,
and the interrupt that stops a retry.
"""

import json
from collections import Counter
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.llm.providers.tools import client as tool_client
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests.integration.test_a_retry_narrows_only_what_has_finished import (
    _stopped_at_the_readers_record,
    _the_first_action_fails_every_record,
)
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    WORKFLOW,
    _disposition,
    _record_ids,
    chained,  # noqa: F401
    project,  # noqa: F401
)


def _run(*args):
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])


def _retry(*args):
    return CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, *args])


def _io(project):  # noqa: F811
    return project / "agent_workflow" / WORKFLOW / "agent_io"


def _status(project, action):  # noqa: F811
    return json.loads((_io(project) / ".agent_status.json").read_text())[action]["status"]


def _manifest(project):  # noqa: F811
    return _io(project) / "store" / WORKFLOW / "_retry_manifest.json"


def _dispositions(project, action):  # noqa: F811
    return Counter(_disposition(project, guid, action) for guid in _record_ids(project, action))


@contextmanager
def _counting_tool_calls():
    run_tool = tool_client.execute_user_defined_function
    calls = Counter()

    def counting(udf_name, *args, **kwargs):
        calls[udf_name] += 1
        return run_tool(udf_name, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(tool_client, "execute_user_defined_function", counting)
        yield calls


@pytest.fixture
def every_record_failed(chained):  # noqa: F811
    """`flatten` failed every record, which leaves it a node-level failure too."""
    with _the_first_action_fails_every_record():
        _run("--fresh")
    assert (_status(chained, ACTION), _status(chained, SECOND)) == ("failed", "skipped")
    assert _disposition(chained, NODE_LEVEL_RECORD_ID) == "failed"
    return chained


@pytest.fixture
def interrupted(every_record_failed):
    """A retry that answered every record at `flatten`, then was stopped in `enrich`."""
    root = every_record_failed
    with _stopped_at_the_readers_record(KeyboardInterrupt(), nth=3):
        _retry()
    assert (_status(root, ACTION), _status(root, SECOND)) == ("completed", "interrupted")
    assert _dispositions(root, ACTION) == {"success": RECORDS}
    assert _manifest(root).exists()
    return root


def test_a_dry_run_puts_nothing_back(interrupted):
    result = _retry("--dry-run")

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output, result.output
    assert _manifest(interrupted).exists()
    assert _dispositions(interrupted, ACTION) == {"success": RECORDS}
    assert _disposition(interrupted, NODE_LEVEL_RECORD_ID) is None


def test_a_dry_run_shows_the_retry_that_would_resume(interrupted):
    """The plan counts what a retry would put back, though the dry run puts none of it."""
    result = _retry("--dry-run")

    assert f"Records to retry: {RECORDS}" in result.output, result.output


def test_a_plain_run_after_a_dry_run_answers_nothing_twice(interrupted):
    _retry("--dry-run")

    with _counting_tool_calls() as calls:
        result = _run()

    assert result.exit_code == 0, result.output
    assert calls["flatten_pages"] == 0
    assert _dispositions(interrupted, SECOND) == {"success": RECORDS}


def test_a_retry_that_stops_before_running_leaves_flatten_finished(interrupted):
    """Nothing failed at `enrich`, so this retry stops once it has put the failures back.
    A node-level failure among them would make `flatten` run again under the next plain run."""
    result = _retry("--from", SECOND)

    assert result.exit_code == 0, result.output
    assert "Nothing to retry" in result.output, result.output
    assert _disposition(interrupted, NODE_LEVEL_RECORD_ID) is None
    with _counting_tool_calls() as calls:
        assert _run().exit_code == 0
    assert calls["flatten_pages"] == 0


def test_retrying_again_resumes_the_interrupted_retry(interrupted):
    """`enrich` holds no failure to start from: what it had not answered is a casualty of
    `flatten`'s, so the next retry starts where the interrupted one did."""
    result = _retry()

    assert result.exit_code == 0, result.output
    assert _dispositions(interrupted, ACTION) == {"success": RECORDS}
    assert _dispositions(interrupted, SECOND) == {"success": RECORDS}
    assert not _manifest(interrupted).exists()


def test_a_retry_after_one_that_finished_puts_nothing_back(every_record_failed):
    """Stopped after its run reached the end, before it deleted its snapshot: what each
    action holds is newer than that snapshot."""
    root = every_record_failed
    with patch("agent_actions.cli.retry._classify_outcome", side_effect=KeyboardInterrupt):
        _retry()
    assert (_status(root, ACTION), _status(root, SECOND)) == ("completed", "completed")
    assert _manifest(root).exists()

    with _counting_tool_calls() as calls:
        result = _retry()

    assert result.exit_code == 0, result.output
    assert "Nothing to retry" in result.output, result.output
    assert sum(calls.values()) == 0
    assert _dispositions(root, ACTION) == {"success": RECORDS}
