"""A database source keeps the rows a query returned; the first stage walks them as files."""

import datetime
import json
import sqlite3
from pathlib import Path

import pytest

from agent_actions.connections.sqlite import SqliteConnector
from agent_actions.errors import ConfigurationError
from agent_actions.input.loaders.data_source import resolve_start_node_data_source
from agent_actions.input.loaders.database_source import snapshot_query

SOURCE = {"type": "database", "connection": "warehouse", "sql": "SELECT id, topic FROM topics"}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "agent_actions.yml").write_text(
        "connections:\n  warehouse:\n    type: sqlite\n    path: warehouse.db\n", encoding="utf-8"
    )
    with sqlite3.connect(tmp_path / "warehouse.db") as raw:
        raw.execute("CREATE TABLE topics (id INTEGER, topic TEXT)")
        raw.executemany("INSERT INTO topics VALUES (?, ?)", [(n, f"topic {n}") for n in range(5)])
    (tmp_path / "agent_io").mkdir()
    return tmp_path


def _documents(directory: Path) -> dict[str, list[dict]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.iterdir())
    }


def _resolve(project: Path, **changes) -> Path:
    result = resolve_start_node_data_source(project / "agent_io", {**SOURCE, **changes}, "first")
    (directory,) = result.directories
    return directory


def test_the_rows_are_staged_as_documents_of_records(project):
    documents = _documents(_resolve(project))

    assert documents == {"part-00000.json": [{"id": n, "topic": f"topic {n}"} for n in range(5)]}


def test_the_rows_are_split_into_files_of_chunk_rows(project):
    documents = _documents(_resolve(project, chunk_rows=2))

    assert [len(rows) for rows in documents.values()] == [2, 2, 1]
    assert list(documents) == ["part-00000.json", "part-00001.json", "part-00002.json"]


def test_a_second_resolution_reads_the_snapshot_not_the_database(project):
    first = _resolve(project)
    (project / "warehouse.db").unlink()

    assert _documents(_resolve(project)) == _documents(first)


def test_a_dropped_snapshot_is_read_again_with_the_rows_added_since(project):
    snapshot = _resolve(project)
    with sqlite3.connect(project / "warehouse.db") as raw:
        raw.execute("INSERT INTO topics VALUES (5, 'topic 5')")
    for document in snapshot.iterdir():
        document.unlink()
    snapshot.rmdir()

    assert len(_documents(_resolve(project))["part-00000.json"]) == 6


def test_another_query_keeps_a_snapshot_of_its_own(project):
    assert _resolve(project) != _resolve(project, sql="SELECT id FROM topics WHERE id > 2")


def test_a_query_that_fails_leaves_no_snapshot_behind(project):
    with pytest.raises(ConfigurationError, match="no such table"):
        _resolve(project, sql="SELECT * FROM missing")

    assert not list((project / "agent_io").rglob("data"))


def test_a_read_that_stops_partway_leaves_no_snapshot_behind(tmp_path: Path):
    class Stops(SqliteConnector):
        def read(self, query):
            yield {"id": 1}
            raise ConfigurationError("the connection dropped")

    with pytest.raises(ConfigurationError, match="dropped"):
        snapshot_query(Stops(tmp_path / "w.db"), "SELECT 1", tmp_path / "data", chunk_rows=1)

    assert not (tmp_path / "data").exists()


def test_a_value_json_cannot_hold_is_staged_in_its_json_form(tmp_path: Path):
    class Dated(SqliteConnector):
        def read(self, query):
            yield {"id": 1, "at": datetime.date(2026, 11, 23)}

    snapshot_query(Dated(tmp_path / "w.db"), "SELECT 1", tmp_path / "data")

    assert _documents(tmp_path / "data") == {"part-00000.json": [{"id": 1, "at": "2026-11-23"}]}


@pytest.mark.parametrize("missing", ["connection", "sql"])
def test_a_database_source_needs_a_connection_and_a_query(project, missing):
    source = {key: value for key, value in SOURCE.items() if key != missing}

    with pytest.raises(ConfigurationError, match="requires a 'connection' and an 'sql' query"):
        resolve_start_node_data_source(project / "agent_io", source, "first")
