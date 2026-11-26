"""A database source keeps the rows a query returned; the first stage walks them as files."""

import datetime
import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_actions.connections import WriteMode
from agent_actions.connections.sqlite import SqliteConnector
from agent_actions.errors import ConfigurationError
from agent_actions.input.loaders.data_source import resolve_start_node_data_source
from agent_actions.input.loaders.database_source import request_refresh, snapshot_query

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


def _staged(directory: Path) -> list[dict]:
    rows = [row for document in _documents(directory).values() for row in document]
    return sorted(rows, key=lambda row: row["id"])


def _file_of(directory: Path) -> dict[int, str]:
    return {row["id"]: name for name, rows in _documents(directory).items() for row in rows}


def test_the_rows_are_staged_as_documents_of_records(project):
    assert _staged(_resolve(project)) == [{"id": n, "topic": f"topic {n}"} for n in range(5)]


def test_the_rows_are_spread_over_no_more_files_than_asked(project):
    assert len(_documents(_resolve(project, files=2))) <= 2
    assert list(_documents(_resolve(project, sql="SELECT id FROM topics", files=1))) == [
        "part-00000.json"
    ]


def test_a_second_resolution_reads_the_snapshot_not_the_database(project):
    first = _staged(_resolve(project))
    (project / "warehouse.db").unlink()

    assert _staged(_resolve(project)) == first


def test_a_refresh_reads_again_with_the_rows_added_since(project):
    _resolve(project)
    with sqlite3.connect(project / "warehouse.db") as raw:
        raw.execute("INSERT INTO topics VALUES (5, 'topic 5')")
    request_refresh()

    assert len(_staged(_resolve(project))) == 6


def test_a_row_stays_in_its_file_when_the_rows_around_it_come_and_go(project):
    before = _file_of(_resolve(project, files=3))
    with sqlite3.connect(project / "warehouse.db") as raw:
        raw.execute("DELETE FROM topics WHERE id = 0")
        raw.execute("INSERT INTO topics VALUES (9, 'topic 9')")
    request_refresh()

    after = _file_of(_resolve(project, files=3))

    assert {n: after[n] for n in (1, 2, 3, 4)} == {n: before[n] for n in (1, 2, 3, 4)}


def test_a_row_s_file_does_not_depend_on_the_order_of_its_columns(project):
    by_id = _file_of(_resolve(project, files=3))
    swapped = _file_of(_resolve(project, sql="SELECT topic, id FROM topics", files=3))

    assert swapped == by_id


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
        snapshot_query(Stops(tmp_path / "w.db"), "SELECT 1", tmp_path / "data")

    assert not (tmp_path / "data").exists()


def test_a_value_json_cannot_hold_is_staged_in_its_json_form(tmp_path: Path):
    class Dated(SqliteConnector):
        def read(self, query):
            yield {"id": 1, "at": datetime.date(2026, 11, 23)}

    snapshot_query(Dated(tmp_path / "w.db"), "SELECT 1", tmp_path / "data")

    assert _staged(tmp_path / "data") == [{"id": 1, "at": "2026-11-23"}]


@pytest.mark.parametrize("missing", ["connection", "sql"])
def test_a_database_source_needs_a_connection_and_a_query(project, missing):
    source = {key: value for key, value in SOURCE.items() if key != missing}

    with pytest.raises(ConfigurationError, match="requires a 'connection' and an 'sql' query"):
        resolve_start_node_data_source(project / "agent_io", source, "first")


def test_a_connection_pointed_at_another_database_is_read_again(project):
    first = _resolve(project)
    with sqlite3.connect(project / "other.db") as raw:
        raw.execute("CREATE TABLE topics (id INTEGER, topic TEXT)")
        raw.execute("INSERT INTO topics VALUES (99, 'elsewhere')")
    (project / "agent_actions.yml").write_text(
        "connections:\n  warehouse:\n    type: sqlite\n    path: other.db\n", encoding="utf-8"
    )

    second = _resolve(project)

    assert second != first
    assert _staged(second) == [{"id": 99, "topic": "elsewhere"}]


def test_one_snapshot_file_keeps_the_order_the_query_returns(project):
    snapshot = _resolve(project, sql="SELECT id, topic FROM topics ORDER BY id DESC", files=1)

    assert [row["id"] for row in _documents(snapshot)["part-00000.json"]] == [4, 3, 2, 1, 0]


def test_more_snapshot_files_than_the_limit_are_refused(project):
    with pytest.raises(ValidationError, match="less than or equal to 256"):
        _resolve(project, files=257)


def _with_settings(project: Path, settings: str) -> None:
    (project / "agent_actions.yml").write_text(
        f"connections:\n  warehouse:\n    type: sqlite\n{settings}", encoding="utf-8"
    )


def test_a_setting_read_from_the_environment_names_the_snapshot_by_its_value(project, monkeypatch):
    _with_settings(project, "    path: ${WAREHOUSE_FILE}\n")
    monkeypatch.setenv("WAREHOUSE_FILE", "warehouse.db")
    first = _resolve(project)
    with sqlite3.connect(project / "other.db") as raw:
        raw.execute("CREATE TABLE topics (id INTEGER, topic TEXT)")

    monkeypatch.setenv("WAREHOUSE_FILE", "other.db")

    assert _resolve(project) != first


def test_a_credential_names_the_snapshot_by_its_reference_not_its_value():
    from agent_actions.connections.settings import settings_as_resolved

    raw = {"host": "${DB_HOST}", "password": "${DB_PASSWORD}"}
    environ = {"DB_HOST": "db.internal", "DB_PASSWORD": "s3cret-value"}

    assert settings_as_resolved(raw, environ) == {
        "host": "db.internal",
        "password": "${DB_PASSWORD}",
    }


def test_one_file_is_the_default_so_a_file_level_action_gets_every_row(project):
    assert list(_documents(_resolve(project))) == ["part-00000.json"]


def test_a_refresh_that_fails_keeps_the_snapshot_there_was(project):
    first = _staged(_resolve(project))
    (project / "warehouse.db").unlink()
    request_refresh()

    with pytest.raises(ConfigurationError):
        _resolve(project)

    request_refresh()
    with sqlite3.connect(project / "warehouse.db") as raw:
        raw.execute("CREATE TABLE topics (id INTEGER, topic TEXT)")
    assert _staged(_resolve(project)) == []
    assert first


def test_going_back_to_an_earlier_query_reads_it_again(project):
    _resolve(project)
    _resolve(project, sql="SELECT id, topic FROM topics WHERE id < 2")
    with sqlite3.connect(project / "warehouse.db") as raw:
        raw.execute("INSERT INTO topics VALUES (9, 'topic 9')")

    assert 9 in [row["id"] for row in _staged(_resolve(project))]


def test_changing_the_file_count_reads_the_query_again(project):
    one = _resolve(project)
    two = _resolve(project, files=2)

    assert two != one
    assert len(_documents(two)) == 2


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM topics",
        "UPDATE topics SET topic = 'x'",
        "  -- a comment\nDROP TABLE topics",
        "INSERT INTO topics VALUES (1, 'x')",
    ],
)
def test_a_query_that_is_not_a_read_is_refused_and_never_runs(project, sql):
    with pytest.raises(ConfigurationError, match="must be a SELECT"):
        _resolve(project, sql=sql)

    with sqlite3.connect(project / "warehouse.db") as raw:
        assert raw.execute("SELECT count(*) FROM topics").fetchone() == (5,)


@pytest.mark.parametrize(
    "sql",
    [
        "select id from topics",
        "WITH t AS (SELECT id FROM topics) SELECT id FROM t",
        "/* note */ SELECT id FROM topics",
    ],
)
def test_a_read_in_any_form_is_accepted(project, sql):
    assert len(_staged(_resolve(project, sql=sql))) == 5


def test_a_source_connection_cannot_write_even_inside_a_select(project):
    from agent_actions.connections import open_connection

    with open_connection("warehouse", project, read_only=True) as connector:
        with pytest.raises(ConfigurationError, match="opened to read"):
            connector.write("topics", ["id"], [(1,)], mode=WriteMode.APPEND)
        with pytest.raises(ConfigurationError, match="readonly|read-only|read only"):
            list(connector.read("WITH gone AS (SELECT 1) DELETE FROM topics RETURNING id"))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM topics; DELETE FROM topics",
        "SELECT id FROM topics;\n-- then\nDELETE FROM topics WHERE true;",
        "SELECT id FROM topics; /* x */ DROP TABLE topics",
    ],
)
def test_a_second_statement_is_refused_and_never_runs(project, sql):
    # BigQuery runs a query of several statements as a script, and opens no read-only session.
    with pytest.raises(ConfigurationError, match="holds more than one"):
        _resolve(project, sql=sql)

    with sqlite3.connect(project / "warehouse.db") as raw:
        assert raw.execute("SELECT count(*) FROM topics").fetchone() == (5,)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM topics;",
        "SELECT id FROM topics ;  -- the end\n",
        "SELECT id FROM topics WHERE topic != 'a;b'",
        'SELECT id, topic AS "a;b" FROM topics',
        "SELECT id FROM topics /* a; b */",
    ],
)
def test_a_semicolon_that_ends_the_statement_or_sits_in_a_text_is_accepted(project, sql):
    assert len(_staged(_resolve(project, sql=sql))) == 5
