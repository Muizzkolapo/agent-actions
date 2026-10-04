"""A failure `agac retry` cannot reach is still a failure after it.

Retry clears what it names at the action it starts from, then re-runs that action
narrowed to the records whose source_guid it named. An id no record arrives with is
cleared and never found: a failure an earlier release recorded under a batch record's
target_id, one set by hand, or a record whose input is gone. Nothing repaired it, and
the action read complete over it.

Driven through the `agac` CLI against the real store: in process for a tool action,
and in its own process with the provider mock for a batch one.
"""

import copy
import json

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration import test_retry_selection_under_batch as under_batch
from tests.integration.test_a_file_tool_that_invents_rows import inventing  # noqa: F401
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    WORKFLOW,
    _backend,
    _disposition,
    _fail,
    _record_ids,
    project,  # noqa: F401
)
from tests.integration.test_retry_selection_under_batch import (
    submitted_and_collected,  # noqa: F401
)

# The id an earlier release recorded a batch record with no source_guid under.
LEGACY = "t-legacy"


def _retry(*args):
    return CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, *args])


def _status(root, action=ACTION, workflow=WORKFLOW):
    path = root / "agent_workflow" / workflow / "agent_io" / ".agent_status.json"
    return json.loads(path.read_text())[action]["status"]


def _input(root):
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"


def test_a_failure_under_an_id_no_input_carries_stands_after_a_retry(project):  # noqa: F811
    _fail(project, LEGACY)

    result = _retry()

    assert result.exit_code == 0, result.output
    assert _disposition(project, LEGACY) == "failed"


def test_the_next_retry_still_names_it(project):  # noqa: F811
    _fail(project, LEGACY)
    _retry()

    result = _retry("--dry-run")

    assert "Records to retry: 1" in result.output, result.output


def test_the_action_reads_the_failure_it_still_holds(project):  # noqa: F811
    _fail(project, LEGACY)

    _retry()

    assert _status(project) == "completed_with_failures"


def test_the_retry_says_it_repaired_nothing_for_it(project):  # noqa: F811
    _fail(project, LEGACY)

    result = _retry()

    said = under_batch._unwrapped(result.output)
    assert (
        f"were not in its input, so nothing repaired them and their failures stand: {LEGACY}."
        in said
    ), said
    assert "agac run --fresh" in said, said


def test_a_record_the_retry_reaches_is_repaired_beside_one_it_cannot(project):  # noqa: F811
    reached = _record_ids(project)[0]
    _fail(project, reached)
    _fail(project, LEGACY)

    result = _retry()

    assert result.exit_code == 0, result.output
    assert (_disposition(project, reached), _disposition(project, LEGACY)) == ("success", "failed")


def test_a_record_whose_input_is_gone_keeps_its_failure(project):  # noqa: F811
    """`--record` names exactly the record it names, and finding none of its input is
    no more a repair of it than an id no record carries."""
    named = _record_ids(project)[-1]
    _fail(project, named)
    _input(project).unlink()

    result = _retry("--record", named)

    assert result.exit_code == 0, result.output
    assert _disposition(project, named) == "failed"


def test_an_action_holding_nothing_but_such_a_failure_reads_failed(project):  # noqa: F811
    """What an earlier release left for a batch file none of whose records had a
    source_guid: failures under target ids and no success. The action read failed
    before the retry, and the retry repaired nothing."""
    backend = _backend(project)
    try:
        backend.clear_disposition(ACTION)
    finally:
        backend.close()
    _fail(project, LEGACY)

    result = _retry()

    assert result.exit_code == 1, result.output
    assert (_status(project), _disposition(project, LEGACY)) == ("failed", "failed")


def test_a_record_a_file_tool_rolled_up_is_not_put_back(inventing):  # noqa: F811
    """Rolled into rows no single input produced, it gets no disposition of its own.
    The retry found it and the tool answered it, so its failure is not put back."""
    named = _record_ids(inventing, ACTION)[0]
    _fail(inventing, named, "roll_up")

    result = _retry()

    assert result.exit_code == 0, result.output
    assert _disposition(inventing, named, "roll_up") is None
    assert "were not in its input" not in result.output


def _hold_a_failure_under_its_target_id(root):
    """What an earlier release left for a batch record with no source_guid: a failed
    row and a failed disposition, both under the record's target_id."""
    backend = under_batch._backend(root)
    try:
        (path,) = backend.list_target_files(under_batch.ACTION)
        rows = backend._read_target_raw(under_batch.ACTION, path)
        failed = {
            **copy.deepcopy(rows[0]),
            "source_guid": LEGACY,
            "target_id": LEGACY,
            "_state": "failed",
        }
        backend._write_target_raw(under_batch.ACTION, path, [*rows, failed])
        backend.set_disposition(
            under_batch.ACTION, LEGACY, "failed", reason="recorded by an earlier release"
        )
    finally:
        backend.close()


def test_a_batch_retry_leaves_a_failure_under_a_target_id_standing(
    submitted_and_collected,  # noqa: F811
):
    root = submitted_and_collected
    _hold_a_failure_under_its_target_id(root)

    code, output = under_batch._agac(root, "retry", "-a", under_batch.WORKFLOW)

    assert code == 0, output
    assert under_batch._dispositions(root)[LEGACY] == "failed"
    assert _status(root, under_batch.ACTION, under_batch.WORKFLOW) == "completed_with_failures"
