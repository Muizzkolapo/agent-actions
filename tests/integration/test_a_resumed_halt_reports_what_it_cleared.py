"""A retry resuming a halt in full reports the records it cleared by what the run did.

It cleared the failures at the halted action and narrowed nothing, so nothing noted what
the run found or answered for them. A record in a file that failed during the resume was
said to be "not in its input", to be cleared only with `agac run --fresh`; and a record a
FILE tool answered with invented rows was put back as failed though its file was processed
to the end, leaving the action `completed_with_failures` (1329).
"""

import json

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_retry_runs_a_file_tool_over_its_whole_file import (
    _FILE_TOOL_HEAD,
    ONLINE,
    WORKFLOW,
    _backend,
    _env,
    _project,
)

# One invented row per file. Halts on file b and breaks on file a while the flag files exist.
_INVENTING_ROLL_UP = (
    _FILE_TOOL_HEAD
    + """

@udf_tool(granularity=Granularity.FILE)
def roll_pages(data: list) -> FileUDFResult:
    pages = _handed(data)
    root = Path(os.environ["ROLL_DIR"])
    if (root / "halt_b").exists() and "Page gamma." in pages:
        from agent_actions.errors import exhaustion_halt

        raise exhaustion_halt("Retry exhausted after 2 attempts (on_exhausted=raise)")
    if (root / "break_a").exists() and "Page alpha." in pages:
        raise RuntimeError("the roll-up of file a broke")
    return FileUDFResult(
        outputs=[
            {
                "source_index": None,
                "data": {"summary": " + ".join(sorted(pages)), "exam_density": "low"},
            }
        ]
    )
"""
)


def _agac(project, *args):
    result = run_agac(project, *args, "-a", WORKFLOW, env=_env(project))
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def _status(project, action="roll_up"):
    status = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status.read_text()).get(action, {}).get("status")


def _disposition(project, record_id, action="roll_up"):
    backend = _backend(project)
    try:
        rows = [r for r in backend.get_disposition(action) if r["record_id"] == record_id]
        return rows[0]["disposition"] if rows else None
    finally:
        backend.close()


@pytest.fixture
def halted(tmp_path):
    """`roll_up` halted on file b with file a stored, and one of a's records failed at it
    before the halt."""
    project = _project(tmp_path, ONLINE, _INVENTING_ROLL_UP)
    (project / "halt_b").touch()
    code, output = _agac(project, "run", "--fresh")
    assert code != 0, output
    assert _status(project) == "failed", output
    (project / "halt_b").unlink()
    backend = _backend(project)
    try:
        assert backend.list_target_files("roll_up") == ["pages1.json"]
        # A record of file a, failed at roll_up before the halt: its row is invented, so
        # the record holds no disposition of its own at roll_up until one is put there.
        failed_before = backend.read_target("flatten", "pages1.json")[0]["source_guid"]
        backend.set_disposition("roll_up", failed_before, "failed", reason="before the halt")
    finally:
        backend.close()
    return project, failed_before


def test_a_file_that_fails_during_the_resume_is_named_not_fresh(halted):
    project, failed_before = halted
    (project / "break_a").touch()

    code, output = _agac(project, "retry")

    assert code == 0, output
    # The run failed it itself, over the file's error; nothing is put back and
    # nothing says the record was not in its input.
    assert _disposition(project, failed_before) == "failed"
    assert "not in its input" not in output, output
    assert "--fresh" not in output, output


def test_a_record_answered_by_an_invented_row_is_not_put_back(halted):
    project, failed_before = halted

    code, output = _agac(project, "retry")

    assert code == 0, output
    assert _status(project) == "completed", output
    assert _disposition(project, failed_before) != "failed"
    assert "failures stand" not in output, output
