"""The reference connector: what any connector's read and write are held to."""

import sqlite3
from pathlib import Path

import pytest

from agent_actions.connections import WriteMode, open_connection
from agent_actions.connections.sqlite import SqliteConnector
from agent_actions.errors import ConfigurationError

COLUMNS = ["id", "label"]


@pytest.fixture
def connector(tmp_path: Path):
    with SqliteConnector(tmp_path / "warehouse.db") as connector:
        yield connector


def _held(connector: SqliteConnector, table: str = "labels") -> list[tuple]:
    return sorted(tuple(row.values()) for row in connector.read(f'SELECT * FROM "{table}"'))


def test_a_query_reads_rows_keyed_by_column(tmp_path: Path):
    database = tmp_path / "warehouse.db"
    with sqlite3.connect(database) as raw:
        raw.execute("CREATE TABLE topics (id INTEGER, topic TEXT)")
        raw.execute("INSERT INTO topics VALUES (1, 'volcanoes')")

    with SqliteConnector(database) as connector:
        assert list(connector.read("SELECT id, topic FROM topics")) == [
            {"id": 1, "topic": "volcanoes"}
        ]


def test_a_query_the_database_refuses_names_the_query(connector):
    with pytest.raises(ConfigurationError, match="no such table"):
        list(connector.read("SELECT * FROM missing"))


def test_a_write_creates_the_table_it_names(connector):
    written = connector.write("labels", COLUMNS, [(1, "a"), (2, "b")], mode=WriteMode.APPEND)

    assert written == 2
    assert _held(connector) == [(1, "a"), (2, "b")]


def test_an_append_keeps_the_rows_already_there(connector):
    connector.write("labels", COLUMNS, [(1, "a")], mode=WriteMode.APPEND)
    connector.write("labels", COLUMNS, [(1, "a")], mode=WriteMode.APPEND)

    assert _held(connector) == [(1, "a"), (1, "a")]


def test_a_replace_leaves_only_the_new_rows(connector):
    connector.write("labels", COLUMNS, [(1, "a"), (2, "b")], mode=WriteMode.APPEND)
    connector.write("labels", COLUMNS, [(3, "c")], mode=WriteMode.REPLACE)

    assert _held(connector) == [(3, "c")]


def test_a_write_of_no_rows_creates_no_table(connector):
    assert connector.write("labels", ["id"], [], mode=WriteMode.REPLACE) == 0

    connector.write("labels", COLUMNS, [(1, "a")], mode=WriteMode.APPEND)
    assert _held(connector) == [(1, "a")]


def test_a_replace_with_no_rows_empties_a_table_that_holds_more_columns(connector):
    connector.write("labels", COLUMNS, [(1, "a")], mode=WriteMode.APPEND)

    assert connector.write("labels", ["id"], [], mode=WriteMode.REPLACE) == 0
    assert _held(connector) == []


def test_a_merge_written_twice_leaves_the_table_as_once(connector):
    for _ in range(2):
        connector.write("labels", COLUMNS, [(1, "a"), (2, "b")], mode=WriteMode.MERGE, key=["id"])

    assert _held(connector) == [(1, "a"), (2, "b")]


def test_a_merge_replaces_the_row_sharing_a_key_and_keeps_the_rest(connector):
    connector.write("labels", COLUMNS, [(1, "a"), (2, "b")], mode=WriteMode.MERGE, key=["id"])
    connector.write("labels", COLUMNS, [(2, "B"), (3, "c")], mode=WriteMode.MERGE, key=["id"])

    assert _held(connector) == [(1, "a"), (2, "B"), (3, "c")]


def test_a_merge_matches_a_key_that_is_null(connector):
    for _ in range(2):
        connector.write("labels", COLUMNS, [(None, "a")], mode=WriteMode.MERGE, key=["id"])

    assert list(connector.read("SELECT count(*) AS held FROM labels")) == [{"held": 1}]


def test_a_merge_without_a_key_is_refused(connector):
    with pytest.raises(ConfigurationError, match="key columns"):
        connector.write("labels", COLUMNS, [(1, "a")], mode=WriteMode.MERGE)


def test_a_table_lacking_a_column_is_refused_and_left_as_it_was(connector):
    connector.write("labels", COLUMNS, [(1, "a")], mode=WriteMode.APPEND)

    with pytest.raises(ConfigurationError, match="no column score"):
        connector.write("labels", [*COLUMNS, "score"], [(2, "b", 0.5)], mode=WriteMode.REPLACE)

    assert _held(connector) == [(1, "a")]


def test_a_row_the_database_refuses_writes_none_of_the_rows(connector):
    rows = [(1, "a"), (2, object())]

    with pytest.raises(ConfigurationError, match="nothing was written"):
        connector.write("labels", COLUMNS, rows, mode=WriteMode.APPEND)

    assert list(connector.read("SELECT count(*) AS held FROM sqlite_master")) == [{"held": 0}]


@pytest.mark.parametrize("name", ["labels; DROP TABLE topics", 'la"bels', "", "a..b", "1st"])
def test_a_name_that_is_not_an_identifier_is_refused(connector, name):
    with pytest.raises(ConfigurationError, match="not a table or column name"):
        connector.write(name, COLUMNS, [(1, "a")], mode=WriteMode.APPEND)


def _project(tmp_path: Path, connections: str) -> Path:
    (tmp_path / "agent_actions.yml").write_text(connections, encoding="utf-8")
    return tmp_path


def test_a_connection_is_opened_by_the_name_the_project_gives_it(tmp_path: Path):
    project = _project(tmp_path, "connections:\n  warehouse:\n    type: sqlite\n    path: w.db\n")

    with open_connection("warehouse", project) as connector:
        connector.check()

    assert (project / "w.db").exists()


def test_an_undeclared_connection_names_the_declared_ones(tmp_path: Path):
    project = _project(tmp_path, "connections:\n  warehouse:\n    type: sqlite\n    path: w.db\n")

    with pytest.raises(ConfigurationError, match=r"No connection named 'lake'.*warehouse"):
        open_connection("lake", project)


def test_an_unknown_connection_type_names_the_types(tmp_path: Path):
    project = _project(tmp_path, "connections:\n  warehouse:\n    type: oracle\n")

    with pytest.raises(ConfigurationError, match="type 'oracle'; the types are sqlite"):
        open_connection("warehouse", project)
