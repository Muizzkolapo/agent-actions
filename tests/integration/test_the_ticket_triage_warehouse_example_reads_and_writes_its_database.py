"""The ticket_triage_warehouse example, run the ways a team runs it, offline on SQLite.

A first run fills its three tables. A second run changes nothing. A refresh after
the source changed answers only the new and changed tickets, adds the optional
`escalation` column the first time a ticket needs it, and keeps the digest one row.
"""

import importlib.util
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import REPO, run_agac

EXAMPLE = REPO / "examples" / "ticket_triage_warehouse"
WORKFLOW = "ticket_triage_warehouse"


def _agac(project: Path, *args: str) -> str:
    result = run_agac(project, *args, "-a", WORKFLOW)
    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 0, output[-3000:]
    return output


def _sql(project: Path, statement: str) -> list[tuple]:
    with sqlite3.connect(project / "warehouse.db") as warehouse:
        return warehouse.execute(statement).fetchall()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / WORKFLOW
    shutil.copytree(EXAMPLE, project)
    spec = importlib.util.spec_from_file_location("seed_warehouse", project / "seed_warehouse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.seed(project / "warehouse.db")
    return project


def test_a_run_writes_one_routing_row_a_ticket_and_one_digest_row(project):
    _agac(project, "run")

    assert [row[0] for row in _sql(project, "SELECT ticket_id FROM ticket_routing ORDER BY 1")] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert _sql(project, "SELECT count(*) FROM triage_log") == [(5,)]
    assert [row[0] for row in _sql(project, "SELECT tickets FROM routing_digest")] == [5]


def test_a_second_run_and_an_export_change_no_table(project):
    _agac(project, "run")
    tables = ("ticket_routing", "triage_log", "routing_digest")
    before = {table: sorted(_sql(project, f"SELECT * FROM {table}")) for table in tables}

    assert "already complete" in _agac(project, "run")
    _agac(project, "export")

    assert {table: sorted(_sql(project, f"SELECT * FROM {table}")) for table in tables} == before


def test_a_refresh_answers_only_what_changed_and_adds_the_escalation_column(project):
    _agac(project, "run")
    _sql(project, "INSERT INTO tickets VALUES (6, 'Refund', 'I want a refund for May')")
    _sql(project, "UPDATE tickets SET body = 'The app crashes since 2.1' WHERE ticket_id = 2")

    output = _agac(project, "run", "--refresh-input")

    assert "classify 2 records" in output, output
    assert _sql(project, "SELECT escalation FROM ticket_routing WHERE ticket_id = 6") == [
        ("refund requested",)
    ]
    assert _sql(project, "SELECT escalation FROM ticket_routing WHERE ticket_id = 1") == [(None,)]
    assert [row[0] for row in _sql(project, "SELECT tickets FROM routing_digest")] == [6]


def test_a_query_that_would_change_the_source_is_refused_and_changes_nothing(project):
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    query = "SELECT ticket_id, subject, body FROM tickets"
    config.write_text(config.read_text().replace(query, "DELETE FROM tickets"))

    result = run_agac(project, "run", "-a", WORKFLOW)

    assert result.returncode != 0
    assert "must be a SELECT" in result.stdout + result.stderr
    assert _sql(project, "SELECT count(*) FROM tickets") == [(5,)]
