"""A workflow whose input is a query and whose results land in tables of the same database.

The question_rounds example, offline, with its staged file replaced by a `topics` table.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "question_rounds"
WORKFLOW = "question_rounds"
CONFIG = Path("agent_workflow") / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
IO = Path("agent_workflow") / WORKFLOW / "agent_io"

FILE_SOURCE = """    type: local
    folder: ./staging
    file_type: [json]"""
DATABASE_SOURCE = """    type: database
    connection: warehouse
    sql: SELECT id, topic, bar FROM topics"""
OUTPUTS = """
outputs:
  - action: publish
    connection: warehouse
    table: published
    carry: [id]
    key: [id]
  - action: flag_for_review
    connection: warehouse
    table: flagged
    mode: replace
    carry: [id]
"""
CONNECTIONS = "connections:\n  warehouse:\n    type: sqlite\n    path: warehouse.db\n"


def _agac(project: Path, *args: str) -> str:
    result = run_agac(project, *args, "-a", WORKFLOW)
    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 0, output[-3000:]
    return output


def _sql(project: Path, statement: str, *values) -> list[tuple]:
    with sqlite3.connect(project / "warehouse.db") as raw:
        return raw.execute(statement, values).fetchall()


def _published(project: Path) -> list[tuple]:
    return _sql(project, "SELECT id, status, summary FROM published ORDER BY id")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / WORKFLOW
    shutil.copytree(EXAMPLE, project)
    shutil.rmtree(project / IO / "staging")
    config = (project / CONFIG).read_text(encoding="utf-8")
    assert FILE_SOURCE in config
    (project / CONFIG).write_text(
        config.replace(FILE_SOURCE, DATABASE_SOURCE) + OUTPUTS, encoding="utf-8"
    )
    with (project / "agent_actions.yml").open("a", encoding="utf-8") as settings:
        settings.write(CONNECTIONS)
    _sql(project, "CREATE TABLE topics (id INTEGER, topic TEXT, bar INTEGER)")
    for row in [(1, "photosynthesis", 1), (2, "plate tectonics", 2), (3, "the water cycle", 9)]:
        _sql(project, "INSERT INTO topics VALUES (?, ?, ?)", *row)
    return project


def test_the_rows_of_the_query_are_answered_and_written_to_their_tables(project):
    output = _agac(project, "run")

    assert "Wrote 2 rows to published" in output, output
    assert "Wrote 1 rows to flagged" in output, output
    assert _published(project) == [
        (1, "published", "photosynthesis: passed in round 1"),
        (2, "published", "plate tectonics: passed in round 2"),
    ]
    assert _sql(project, "SELECT id, status FROM flagged") == [(3, "needs review")]


def test_a_second_run_and_an_export_leave_the_tables_as_they_were(project):
    _agac(project, "run")
    held = _published(project)

    assert "already complete" in _agac(project, "run")
    _agac(project, "export")

    assert _published(project) == held
    assert _sql(project, "SELECT count(*) FROM flagged") == [(1,)]


def test_only_the_rows_added_or_changed_since_the_snapshot_are_answered_again(project):
    _agac(project, "run")
    _sql(project, "INSERT INTO topics VALUES (4, 'volcanoes', 1)")
    _sql(project, "UPDATE topics SET bar = 1 WHERE id = 2")

    assert "already complete" in _agac(project, "run")
    output = _agac(project, "run", "--refresh-input")

    assert "✓ spec 2 records" in output, output
    assert _published(project) == [
        (1, "published", "photosynthesis: passed in round 1"),
        (2, "published", "plate tectonics: passed in round 1"),
        (4, "published", "volcanoes: passed in round 1"),
    ]


def test_an_export_of_one_action_writes_only_its_table(project):
    _agac(project, "run")
    _sql(project, "DELETE FROM published")
    _sql(project, "DELETE FROM flagged")

    output = _agac(project, "export", "-A", "publish")

    assert "Wrote 2 rows to published" in output and "flagged" not in output, output
    assert _sql(project, "SELECT count(*) FROM flagged") == [(0,)]


def test_a_row_that_leaves_the_query_takes_no_other_row_back_to_the_model(project):
    _agac(project, "run")
    _sql(project, "DELETE FROM topics WHERE id = 1")

    output = _agac(project, "run", "--refresh-input")

    assert "✓ spec 0 records" in output, output
    assert "will reprocess" not in output, output


def test_a_write_that_fails_says_the_results_are_stored_and_how_to_write_them(project):
    _sql(project, "CREATE TABLE published (unrelated TEXT)")

    result = run_agac(project, "run", "-a", WORKFLOW)
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode != 0
    assert "Every action finished, but writing the outputs failed" in output, output
    assert f"agac export -w {WORKFLOW}" in output, output

    _sql(project, "DROP TABLE published")
    assert "Wrote 2 rows to published" in _agac(project, "export")


TOOLS = Path("tools") / WORKFLOW / "question_tools.py"
READ_SPEC = 'def read_spec(data: Any, *args) -> dict:\n    source = data["source"]\n'


def test_a_retry_that_repairs_a_record_writes_it_to_the_table(project):
    tools = project / TOOLS
    text = tools.read_text(encoding="utf-8")
    assert READ_SPEC in text
    tools.write_text(
        "from pathlib import Path\n"
        + text.replace(
            READ_SPEC,
            READ_SPEC
            + '    if source["topic"] == "photosynthesis" and Path(__file__).with_name("fail").exists():\n'
            + '        raise ValueError("refused on purpose")\n',
        ),
        encoding="utf-8",
    )
    (tools.parent / "fail").touch()
    first = run_agac(project, "run", "-a", WORKFLOW)
    assert first.returncode != 0, first.stdout + first.stderr
    assert [row[0] for row in _published(project)] == [2]

    (tools.parent / "fail").unlink()
    output = _agac(project, "retry")

    assert "Wrote 2 rows to published" in output, output
    assert [row[0] for row in _published(project)] == [1, 2]
