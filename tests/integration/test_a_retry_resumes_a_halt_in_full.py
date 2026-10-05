"""`agac retry` never completes a halted action on the records it names alone.

An action halted by `on_exhausted: raise` stops partway through its records, and a plain
run does not resume it: a retry is the way on. One with records to re-run, failed before
the halt or at the halted action itself, narrowed it to those records like any other
action and completed it there, so the records past the halt were never answered and the
next plain run found nothing to do.

Two tool actions, `flatten` and `enrich`, which reads it, over six staged records. Every
command is a real `agac` invocation; only the faults are stood in for: the halt, raised by
a tool as an exhausted `on_exhausted: raise` policy raises it, a tool that fails a record,
a failure marked on a record of `flatten`, and the interrupt that stops a retry.
"""

import json
from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.errors import exhaustion_halt
from agent_actions.llm.providers.tools import client as tool_client
from agent_actions.record.reasons import HALTED_ON_EXHAUSTED
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests.integration.test_a_retry_narrows_only_what_has_finished import (
    _stopped_at_the_readers_record,
)
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


def _run(*args):
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])


def _retry(*args):
    return CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, *args])


def _status(project, action=SECOND):  # noqa: F811
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text()).get(action, {}).get("status", "pending")


def _halted(project, action=SECOND):  # noqa: F811
    backend = _backend(project)
    try:
        rows = backend.get_disposition(action, record_id=NODE_LEVEL_RECORD_ID)
        return any(row.get("detail") == HALTED_ON_EXHAUSTED for row in rows)
    finally:
        backend.close()


def _unwrapped(output):
    return " ".join(output.split())


@contextmanager
def _the_readers_tool(*, halts_at, fails_at=None, udf="tag_density"):
    """*udf*, `enrich`'s tool unless named, failing its call *fails_at* and halting the
    action at *halts_at*."""
    run_tool = tool_client.execute_user_defined_function
    calls = []

    def faulty(udf_name, *args, **kwargs):
        if udf_name == udf:
            calls.append(udf_name)
            if len(calls) == fails_at:
                raise RuntimeError("the tool blew up")
            if len(calls) == halts_at:
                raise exhaustion_halt("Retry exhausted after 2 attempts (on_exhausted=raise)")
        return run_tool(udf_name, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(tool_client, "execute_user_defined_function", faulty)
        yield


def _halt_the_reader(project, **faults):  # noqa: F811
    with _the_readers_tool(**({"halts_at": 3} | faults)):
        result = _run("--fresh")
    assert result.exit_code != 0, result.output
    assert _status(project) == "failed" and _halted(project), result.output


def _a_failure_at_the_first_action(project):  # noqa: F811
    named = _stored_guids(project, ACTION)[-1]
    _fail(project, named, ACTION)
    return named


@pytest.mark.parametrize("names_it", [True, False], ids=["record", "failures"])
def test_a_retry_with_records_before_the_halt_refuses_and_clears_nothing(chained, names_it):  # noqa: F811
    """The sequence the issue measured: narrowed, `enrich` completed on the one record."""
    _halt_the_reader(chained)
    named = _a_failure_at_the_first_action(chained)

    result = _retry(*(["--record", named] if names_it else []))

    assert result.exit_code != 0, result.output
    said = _unwrapped(result.output)
    assert "enrich (halted)" in said and f"--from {SECOND}" in said, said
    assert _status(chained) == "failed" and _halted(chained)
    assert _disposition(chained, named, ACTION) == "failed"


def test_a_dry_run_says_the_retry_would_be_refused(chained):  # noqa: F811
    _halt_the_reader(chained)
    named = _a_failure_at_the_first_action(chained)

    result = _retry("--record", named, "--dry-run")

    assert result.exit_code == 0, result.output
    said = _unwrapped(result.output)
    assert "would be refused" in said and "enrich (halted)" in said, said
    assert _halted(chained)


def test_the_retry_the_refusal_names_resumes_the_halt_in_full(chained):  # noqa: F811
    """The way out the refusal names, and the repair after it."""
    _halt_the_reader(chained)
    named = _a_failure_at_the_first_action(chained)
    assert _retry("--record", named).exit_code != 0

    resumed = _retry("--from", SECOND)

    assert resumed.exit_code == 0, resumed.output
    assert len(_stored_guids(chained, SECOND)) == RECORDS
    repaired = _retry("--record", named)
    assert repaired.exit_code == 0, repaired.output
    assert _disposition(chained, named, ACTION) == "success"
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


def test_a_retry_with_only_the_halt_to_retry_resumes_it_in_full(chained):  # noqa: F811
    _halt_the_reader(chained)

    result = _retry()

    assert result.exit_code == 0, result.output
    assert "resumes it in full" in _unwrapped(result.output), result.output
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


def _an_interrupted_resume(project):  # noqa: F811
    """A retry from the halt, stopped partway: its snapshot keeps the halt, and `enrich`
    is left interrupted under the stamp that marks it as that retry's to resume."""
    _halt_the_reader(project)
    with _stopped_at_the_readers_record(KeyboardInterrupt(), nth=2):
        assert _retry("--from", SECOND).exit_code != 0
    assert _status(project) == "interrupted" and not _halted(project)
    return _a_failure_at_the_first_action(project)


def test_a_dry_run_after_an_interrupted_resume_still_sees_the_halt(chained):  # noqa: F811
    """The halt is back only in the snapshot, which a dry run plans over but does not
    restore."""
    named = _an_interrupted_resume(chained)

    result = _retry("--record", named, "--dry-run")

    assert result.exit_code == 0, result.output
    said = _unwrapped(result.output)
    assert "would be refused" in said and "(enrich (halted))" in said, said


def test_a_retry_after_an_interrupted_resume_refuses_until_the_halt_is_resumed(chained):  # noqa: F811
    """The stamp spares an action the stopped retry would finish, but that retry was
    resuming a halt, and one naming records would complete it on those alone."""
    named = _an_interrupted_resume(chained)

    refusals = [_retry("--record", named), _retry("--record", named)]

    for refused in refusals:
        assert refused.exit_code != 0, refused.output
        said = _unwrapped(refused.output)
        assert "1 action(s)" in said and "(enrich (halted))" in said, said
        assert "Run the workflow first" not in said and f"--from {SECOND}" in said, said
    assert _halted(chained) and _disposition(chained, named, ACTION) == "failed"
    resumed = _retry("--from", SECOND)
    assert resumed.exit_code == 0, resumed.output
    assert len(_stored_guids(chained, SECOND)) == RECORDS
    repaired = _retry("--record", named)
    assert repaired.exit_code == 0, repaired.output
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


SIDE_ACTION = """  - name: side
    kind: tool
    dependencies: [flatten]
    intent: "Note"
    schema: tool_action_output
    impl: note_side
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""

SIDE_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def note_side(data: Any, *args) -> list[dict]:
    return [{"summary": str((data or {}).get("summary", "")), "exam_density": "side"}]
"""


def test_a_halt_before_the_starting_point_stays_halted_and_the_repair_goes_ahead(chained):  # noqa: F811
    """Only a retry from the halt clears it, so one starting past it completes nothing
    there. `side`, declared after `enrich`, runs before it and feeds nothing."""
    config = chained / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SIDE_ACTION)
    (chained / "tools" / WORKFLOW / "side.py").write_text(SIDE_TOOL)
    with _the_readers_tool(halts_at=3, udf="note_side"):
        assert _run("--fresh").exit_code != 0
    assert _halted(chained, "side") and _status(chained) == "completed"
    named = _stored_guids(chained, SECOND)[-1]
    _fail(chained, named, SECOND)

    result = _retry("--from", SECOND, "--record", named)

    said = _unwrapped(result.output)
    assert f"Actions to re-run: {SECOND} Records" in said, said
    assert "would complete them" not in said and "Failed actions: side" in said, said
    assert _halted(chained, "side")
    assert _disposition(chained, named, SECOND) == "success"
    assert _stored_guids(chained, SECOND) == _stored_guids(chained, ACTION)


@pytest.fixture
def two_files(project):  # noqa: F811
    """The same two actions over the six records staged as two files of three.

    `enrich` writes each file as it finishes it, so one that fails a record in the first
    file and halts in the second holds that failure beside the halt.
    """
    staging = project / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    (staging / "pages.json").unlink()
    for name, pages in (("a.json", range(3)), ("b.json", range(3, RECORDS))):
        (staging / name).write_text(json.dumps([{"page_content": f"page {i}"} for i in pages]))
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
    (project / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)

    _halt_the_reader(project, fails_at=1, halts_at=5)
    backend = _backend(project)
    try:
        assert backend.list_target_files(SECOND) == ["a.json"], "the second file never stored"
    finally:
        backend.close()
    failed = [
        record_id
        for record_id in _record_ids(project, SECOND)
        if _disposition(project, record_id, SECOND) == "failed"
    ]
    assert len(failed) == 1, failed
    return project, failed[0]


def test_a_retry_from_a_halt_that_failed_a_record_answers_every_record(two_files):
    """Narrowed to the record that failed in the first file, `enrich` completed without
    the second file."""
    project, failed = two_files  # noqa: F811

    result = _retry()

    assert result.exit_code == 0, result.output
    assert _status(project) == "completed"
    assert _disposition(project, failed, SECOND) == "success"
    assert _stored_guids(project, SECOND) == _stored_guids(project, ACTION)


def test_a_retry_naming_a_record_at_the_halt_refuses(two_files):
    """`--record` answers that record and no other, so it cannot resume a halt."""
    project, failed = two_files  # noqa: F811

    result = _retry("--record", failed)

    assert result.exit_code != 0, result.output
    said = _unwrapped(result.output)
    assert "enrich (halted)" in said and f"--from {SECOND}" in said, said
    assert _halted(project) and _disposition(project, failed, SECOND) == "failed"
