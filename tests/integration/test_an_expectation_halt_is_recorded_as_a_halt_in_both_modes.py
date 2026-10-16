"""`on_exhausted: raise` on an expectation is a halt: recorded as one, refused on the next run,
and resumed by `agac retry` — in both run modes.

Two staged records and a field check that fails the second it is asked about, so the second
record runs out of iterations. Only `run_mode` differs between the two projects; every command
is a real `agac` invocation against the agac provider mock.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agent_actions.record.reasons import HALTED_ON_EXHAUSTED
from tests._support.agac_cli import run_agac
from tests.integration.test_a_record_out_of_expectation_iterations_reads_alike_in_both_modes import (  # noqa: E501
    WORKFLOW,
    _project,
)


def _agac(project: Path, *args: str) -> tuple[int, str]:
    tools = ("-u", "tools") if args[0] == "run" else ()
    result = run_agac(
        project,
        *args,
        "-a",
        WORKFLOW,
        *tools,
        env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def _until_it_stops(project: Path, first: tuple[str, ...]) -> tuple[int, str]:
    """`agac <first>` and then plain runs, for as long as the action asks to be run again."""
    code, output = _agac(project, *first)
    for _ in range(6):
        if "run again" not in output:
            break
        code, output = _agac(project, "run")
    return code, output


def _store(project: Path) -> sqlite3.Connection:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _records(project: Path) -> list[str]:
    con = _store(project)
    try:
        return sorted(
            row[0]
            for row in con.execute(
                "select disposition from record_disposition "
                "where action_name = 'summarize' and record_id != '__node__'"
            )
        )
    finally:
        con.close()


def _halt_marker(project: Path) -> str | None:
    con = _store(project)
    try:
        rows = con.execute(
            "select detail from record_disposition "
            "where action_name = 'summarize' and record_id = '__node__' and disposition = 'failed'"
        ).fetchall()
    finally:
        con.close()
    return rows[0][0] if rows else "<no node-level failure row>"


def _status(project: Path, action: str) -> str:
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[action]["status"]


@pytest.fixture(params=["online", "batch"])
def halted(request, tmp_path):
    project = _project(tmp_path, request.param, on_exhausted="raise")
    code, output = _until_it_stops(project, ("run", "--fresh"))
    assert code == 1, (request.param, output)
    return request.param, project, output


def test_the_halt_is_recorded_on_the_action(halted):
    mode, project, output = halted

    assert _status(project, "summarize") == "failed", (mode, output)
    assert _halt_marker(project) == HALTED_ON_EXHAUSTED, (mode, output)


def test_the_next_plain_run_refuses_to_run_the_halted_action_again(halted):
    mode, project, _ = halted

    code, output = _agac(project, "run")

    assert code == 1, (mode, output)
    assert "halted on an 'on_exhausted: raise' policy and was not re-run" in output, (mode, output)


def test_the_record_that_broke_its_rule_is_not_stored_as_an_answer(halted):
    mode, project, output = halted

    assert _records(project).count("success") <= 1, (mode, _records(project), output)


def test_agac_retry_answers_the_record_the_halt_stopped_at(halted):
    mode, project, _ = halted

    code, output = _until_it_stops(project, ("retry",))

    assert code == 0, (mode, output)
    assert _records(project) == ["success", "success"], (mode, output)
    assert _status(project, "summarize") == "completed", (mode, output)
