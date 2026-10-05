"""A failure `agac retry` does not repair is still a failure after it.

Retry clears what it names at every action it re-runs, then re-runs them narrowed to
the records whose source_guid it named. A record the first of them never answers was
cleared and never re-decided: a failure an earlier release recorded under a batch
record's target_id, one set by hand, a record whose input is gone, one in a file that
failed, or any of them when the action did not finish. Nothing repaired it, and the
action read complete over it.

Driven through the `agac` CLI against the real store: in process for a tool action,
and in its own process with the provider mock for a batch one.
"""

import copy
import json

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests.integration import test_retry_selection_under_batch as under_batch
from tests.integration.test_a_file_tool_that_invents_rows import inventing  # noqa: F401
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    SECOND,
    WORKFLOW,
    _backend,
    _disposition,
    _fail,
    _record_ids,
    chained,  # noqa: F401
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


def _row(root, record_id, action=ACTION):
    backend = _backend(root)
    try:
        (row,) = backend.get_disposition(action, record_id=record_id)
        return row
    finally:
        backend.close()


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


# Switched by the environment rather than by rewriting the tool: a tool module is imported
# once per process, and a retry run in process would call the one it already holds.
BREAK = "AGAC_TEST_BREAK_THE_TOOL"

BREAKABLE_TOOLS = f'''import os
from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import FileUDFResult, Granularity


@udf_tool(granularity=Granularity.FILE)
def roll_up_or_break(data: Any, *args) -> Any:
    if os.environ.get("{BREAK}") and "apage" in repr(data):
        raise RuntimeError("the roll-up of file a broke")
    return FileUDFResult(
        [{{"source_index": None, "data": {{"summary": "rollup", "exam_density": "high"}}}}]
    )


@udf_tool
def tag_or_break(data: Any, *args) -> list[dict]:
    if os.environ.get("{BREAK}"):
        raise RuntimeError("the tag broke")
    return [{{"summary": str((data or {{}}).get("summary", "")), "exam_density": "high"}}]
'''

ROLL_UP = """  - name: roll_up
    kind: tool
    granularity: File
    dependencies: [flatten]
    intent: "Roll each file up into one row"
    schema: tool_action_output
    impl: roll_up_or_break
    context_scope: { observe: [flatten.summary, source.page_content] }
    expect: { repair: none }
"""

TAG = """  - name: tag
    kind: tool
    dependencies: [flatten]
    intent: "Tag"
    schema: tool_action_output
    impl: tag_or_break
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


def _add_breakable(root, action):
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + action)
    (root / "tools" / WORKFLOW / "breakable.py").write_text(BREAKABLE_TOOLS)
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output


@pytest.fixture
def two_files_rolled_up(project):  # noqa: F811
    """Two staged files flattened, then each rolled up by a FILE tool."""
    staging = _input(project).parent
    _input(project).unlink()
    for name in ("a", "b"):
        staging.joinpath(f"{name}.json").write_text(
            json.dumps([{"page_content": f"{name}page {i}"} for i in range(2)])
        )
    _add_breakable(project, ROLL_UP)
    return project


def _flattened(root, page_content):
    backend = _backend(root)
    try:
        (guid,) = [
            row["source_guid"]
            for path in backend.list_target_files(ACTION)
            for row in backend._read_target_raw(ACTION, path)
            if row["content"]["source"]["page_content"] == page_content
        ]
        return guid
    finally:
        backend.close()


def _fail_in_both_files_then_break_file_a(root, monkeypatch):
    in_a, in_b = _flattened(root, "apage 0"), _flattened(root, "bpage 0")
    _fail(root, in_a, "roll_up")
    _fail(root, in_b, "roll_up")
    monkeypatch.setenv(BREAK, "1")
    return in_a, in_b


def test_a_record_whose_file_failed_in_the_retry_keeps_its_failure(
    two_files_rolled_up, monkeypatch
):
    """The retry found it, but the file holding it failed and the walk carried on to the
    next one, so nothing re-decided it."""
    root = two_files_rolled_up
    in_a, in_b = _fail_in_both_files_then_break_file_a(root, monkeypatch)

    _retry()

    assert (_disposition(root, in_a, "roll_up"), _disposition(root, in_b, "roll_up")) == (
        "failed",
        None,
    )


def test_the_next_retry_names_a_record_whose_file_failed(two_files_rolled_up, monkeypatch):
    root = two_files_rolled_up
    _fail_in_both_files_then_break_file_a(root, monkeypatch)
    _retry()

    result = _retry("--dry-run")

    assert "Records to retry: 1" in result.output, result.output


def test_the_retry_says_the_file_holding_it_failed(two_files_rolled_up, monkeypatch):
    root = two_files_rolled_up
    in_a, _ = _fail_in_both_files_then_break_file_a(root, monkeypatch)

    said = under_batch._unwrapped(_retry().output)

    assert "were in a file 'roll_up' failed to process, so nothing repaired them" in said, said
    assert in_a in said, said
    assert "agac run --fresh" not in said, said


def test_a_record_the_retry_fails_again_keeps_the_new_failure(project, monkeypatch):  # noqa: F811
    """Every record in the file failed, so the file raised after writing them down. The
    record was decided by this run, and what it was cleared of is not put back over that."""
    _add_breakable(project, TAG)
    named = _record_ids(project, "tag")[0]
    _fail(project, named, "tag")
    monkeypatch.setenv(BREAK, "1")

    _retry()

    row = _row(project, named, "tag")
    assert row["disposition"] == "failed"
    assert row["reason"] != "constructed for this test", row


def test_a_retry_of_an_action_that_did_not_finish_says_to_fix_it(project):  # noqa: F811
    """The action failed before it reached the record, which may well be in its input.
    Starting over would pay for every record again and fix nothing."""
    _fail(project, LEGACY)
    _input(project).write_text("{ not json")

    result = _retry()

    said = under_batch._unwrapped(result.output)
    assert result.exit_code == 1, said
    assert _disposition(project, LEGACY) == "failed"
    assert (
        f"were not repaired, because '{ACTION}' did not finish, and their failures stand: "
        f"{LEGACY}. Fix what stopped it and run retry again." in said
    ), said
    assert "agac run --fresh" not in said, said


def test_a_record_the_retry_never_found_keeps_its_failure_below_too(chained):  # noqa: F811
    """Retry clears what it names at every action it re-runs, and a record it never found
    at the first of them reaches none of the others."""
    _fail(chained, LEGACY)
    _fail(chained, LEGACY, SECOND)

    _retry()

    assert (_disposition(chained, LEGACY), _disposition(chained, LEGACY, SECOND)) == (
        "failed",
        "failed",
    )
    assert _status(chained, SECOND) == "completed_with_failures"


def test_an_action_level_failure_is_not_put_back(project):  # noqa: F811
    """It speaks for the action, not a record. Put back, it would have the next run skip
    the action the retry just ran."""
    backend = _backend(project)
    try:
        backend.set_disposition(ACTION, NODE_LEVEL_RECORD_ID, "failed", reason="action failed")
    finally:
        backend.close()
    _fail(project, LEGACY)

    _retry()

    assert (_disposition(project, NODE_LEVEL_RECORD_ID), _disposition(project, LEGACY)) == (
        None,
        "failed",
    )


def test_the_failure_put_back_is_the_one_that_was_cleared(project):  # noqa: F811
    held = {
        "reason": "why it failed",
        "relative_path": "pages",
        "input_snapshot": '{"page_content": "page legacy"}',
        "detail": "what it held",
    }
    backend = _backend(project)
    try:
        backend.set_disposition(ACTION, LEGACY, "failed", **held)
    finally:
        backend.close()

    _retry()

    row = _row(project, LEGACY)
    assert {key: row[key] for key in ("disposition", *held)} == {"disposition": "failed", **held}


def test_a_retry_stopped_after_its_put_back_restores_only_that(project, monkeypatch):  # noqa: F811
    """The next retry restores what an interrupted one left in its manifest. Once the
    re-run has decided a record, putting its old failure back would pay to repair it again."""
    reached = _record_ids(project)[0]
    _fail(project, reached)
    _fail(project, LEGACY)

    def stopped(state_mgr):
        raise RuntimeError("stopped")

    with monkeypatch.context() as patched:
        patched.setattr("agent_actions.cli.retry._classify_outcome", stopped)
        assert _retry().exit_code != 0

    result = _retry()

    assert "Records to retry: 1" in result.output, result.output
    assert (_disposition(project, reached), _disposition(project, LEGACY)) == ("success", "failed")


def test_a_batch_retry_that_reaches_one_record_still_pauses_for_it(
    submitted_and_collected,  # noqa: F811
):
    """Read complete over the failure put back, the action would never collect the batch
    sent for the record the retry did reach."""
    root = submitted_and_collected
    under_batch._set_disposition(root, under_batch._guids(root)[0], "failed")
    under_batch._set_disposition(root, LEGACY, "failed")

    code, output = under_batch._agac(root, "retry", "-a", under_batch.WORKFLOW)

    assert code == 0, output
    assert "run again" in output, output
    assert _status(root, under_batch.ACTION, under_batch.WORKFLOW) == "batch_submitted"


def test_the_run_that_collects_it_repairs_one_and_keeps_the_other(
    submitted_and_collected,  # noqa: F811
):
    root = submitted_and_collected
    reached = under_batch._guids(root)[0]
    under_batch._set_disposition(root, reached, "failed")
    under_batch._set_disposition(root, LEGACY, "failed")

    under_batch._cycle(root, "retry", "-a", under_batch.WORKFLOW)

    dispositions = under_batch._dispositions(root)
    assert (dispositions[reached], dispositions[LEGACY]) == ("success", "failed")
    assert _status(root, under_batch.ACTION, under_batch.WORKFLOW) == "completed_with_failures"


def test_a_failure_put_back_with_no_reason_is_collected_over(
    submitted_and_collected,  # noqa: F811
):
    """One set by hand may carry no reason, and the run that collects the batch logs each
    failure it reads."""
    root = submitted_and_collected
    under_batch._set_disposition(root, under_batch._guids(root)[0], "failed")
    backend = under_batch._backend(root)
    try:
        backend.set_disposition(under_batch.ACTION, LEGACY, "failed")
    finally:
        backend.close()

    under_batch._cycle(root, "retry", "-a", under_batch.WORKFLOW)

    assert under_batch._dispositions(root)[LEGACY] == "failed"
