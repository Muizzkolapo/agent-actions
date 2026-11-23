"""One contract, held against a real database of each type that can run here.

SQLite and DuckDB are files; PostgreSQL and MySQL are servers started for the
session from the machine's own binaries and skipped where there are none. The
types that need an account (BigQuery, Snowflake, Redshift, Databricks) share
this code path and are covered by tests/unit/connections with a stand-in driver.
"""

import datetime
import decimal
import shutil
import uuid
from pathlib import Path

import pytest

from agent_actions.connections import ColumnType, WriteMode, json_safe, open_connection
from agent_actions.errors import ConfigurationError
from tests._support.agac_cli import run_agac
from tests._support.databases import has_driver, mysql_server, postgres_server

COLUMNS = ["id", "label"]
TYPES = {"id": ColumnType.INTEGER, "label": ColumnType.TEXT}


@pytest.fixture(scope="session")
def servers():
    with postgres_server() as postgres, mysql_server() as mysql:
        yield {"postgres": postgres, "mysql": mysql}


@pytest.fixture(params=["sqlite", "duckdb", "postgres", "mysql"])
def settings(request, servers) -> dict:
    kind = request.param
    if kind == "sqlite":
        return {"type": "sqlite", "path": "warehouse.db"}
    if kind == "duckdb":
        if not has_driver("duckdb"):
            pytest.skip("the duckdb driver is not installed")
        return {"type": "duckdb", "path": "warehouse.duckdb"}
    if servers[kind] is None:
        pytest.skip(f"no {kind} server or driver on this machine")
    return servers[kind]


def _declare(project: Path, settings: dict) -> None:
    lines = "".join(f"    {key}: {value}\n" for key, value in settings.items())
    with (project / "agent_actions.yml").open("a", encoding="utf-8") as config:
        config.write(f"connections:\n  warehouse:\n{lines}")


@pytest.fixture
def connector(settings, tmp_path: Path):
    _declare(tmp_path, settings)
    with open_connection("warehouse", tmp_path) as opened:
        yield opened


@pytest.fixture
def table() -> str:
    return f"labels_{uuid.uuid4().hex[:12]}"


def _write(connector, table, rows, mode=WriteMode.APPEND, **options):
    return connector.write(table, COLUMNS, rows, mode=mode, types=TYPES, **options)


def _held(connector, table: str) -> list[tuple]:
    name = connector.dialect.identifier(table)
    return sorted(tuple(row.values()) for row in connector.read(f"SELECT id, label FROM {name}"))


def _exists(connector, table: str) -> bool:
    return connector._held_columns(connector._open(), table) is not None


def test_the_database_answers(connector):
    connector.check()


def test_a_query_reads_rows_keyed_by_column(connector):
    assert list(connector.read("SELECT 1 AS id, 'volcanoes' AS topic")) == [
        {"id": 1, "topic": "volcanoes"}
    ]


def test_a_query_the_database_refuses_names_the_query(connector):
    with pytest.raises(ConfigurationError, match="The query failed") as refused:
        list(connector.read("SELECT * FROM no_such_table_anywhere"))

    assert refused.value.context["query"] == "SELECT * FROM no_such_table_anywhere"


def test_the_connection_is_usable_after_a_query_it_refused(connector):
    with pytest.raises(ConfigurationError):
        list(connector.read("SELECT * FROM no_such_table_anywhere"))

    assert list(connector.read("SELECT 2 AS id")) == [{"id": 2}]


def test_a_result_larger_than_one_fetch_is_read_whole(connector, table):
    _write(connector, table, [(n, f"row {n}") for n in range(2500)])

    assert len(_held(connector, table)) == 2500


def test_a_write_creates_the_table_it_names(connector, table):
    assert _write(connector, table, [(1, "a"), (2, "b")]) == 2
    assert _held(connector, table) == [(1, "a"), (2, "b")]


def test_a_write_of_no_rows_creates_no_table(connector, table):
    assert _write(connector, table, [], mode=WriteMode.REPLACE) == 0
    assert not _exists(connector, table)


def test_an_append_keeps_the_rows_already_there(connector, table):
    _write(connector, table, [(1, "a")])
    _write(connector, table, [(1, "a")])

    assert _held(connector, table) == [(1, "a"), (1, "a")]


def test_a_replace_leaves_only_the_new_rows(connector, table):
    _write(connector, table, [(1, "a"), (2, "b")])
    _write(connector, table, [(3, "c")], mode=WriteMode.REPLACE)

    assert _held(connector, table) == [(3, "c")]


def test_a_replace_with_no_rows_empties_the_table(connector, table):
    _write(connector, table, [(1, "a")])

    assert _write(connector, table, [], mode=WriteMode.REPLACE) == 0
    assert _held(connector, table) == []


def test_a_merge_written_twice_leaves_the_table_as_once(connector, table):
    for _ in range(2):
        _write(connector, table, [(1, "a"), (2, "b")], mode=WriteMode.MERGE, key=["id"])

    assert _held(connector, table) == [(1, "a"), (2, "b")]


def test_a_merge_replaces_the_row_sharing_a_key_and_keeps_the_rest(connector, table):
    _write(connector, table, [(1, "a"), (2, "b")], mode=WriteMode.MERGE, key=["id"])
    _write(connector, table, [(2, "B"), (3, "c")], mode=WriteMode.MERGE, key=["id"])

    assert _held(connector, table) == [(1, "a"), (2, "B"), (3, "c")]


def test_a_merge_on_two_columns_matches_both(connector, table):
    _write(connector, table, [(1, "a"), (1, "b")], mode=WriteMode.MERGE, key=COLUMNS)
    _write(connector, table, [(1, "b"), (2, "b")], mode=WriteMode.MERGE, key=COLUMNS)

    assert _held(connector, table) == [(1, "a"), (1, "b"), (2, "b")]


def test_a_merge_without_a_key_is_refused(connector, table):
    with pytest.raises(ConfigurationError, match="key columns"):
        _write(connector, table, [(1, "a")], mode=WriteMode.MERGE)


def test_a_merge_of_a_row_with_no_key_value_is_refused_and_writes_nothing(connector, table):
    _write(connector, table, [(1, "a")])

    with pytest.raises(ConfigurationError, match="has no value for its key"):
        _write(connector, table, [(2, "b"), (None, "c")], mode=WriteMode.MERGE, key=["id"])

    assert _held(connector, table) == [(1, "a")]


def test_a_table_lacking_a_column_is_refused_and_left_as_it_was(connector, table):
    _write(connector, table, [(1, "a")])

    with pytest.raises(ConfigurationError, match="no column score"):
        connector.write(
            table, [*COLUMNS, "score"], [(2, "b", 0.5)], mode=WriteMode.REPLACE, types=TYPES
        )

    assert _held(connector, table) == [(1, "a")]


def test_a_row_the_database_refuses_leaves_the_rows_before_it_unwritten(connector, table):
    _write(connector, table, [(1, "a")])

    with pytest.raises(ConfigurationError, match=f"Writing to {table} failed"):
        _write(connector, table, [(2, "b"), (3,)], mode=WriteMode.REPLACE)

    assert _held(connector, table) == [(1, "a")]


def test_a_created_table_holds_each_value_in_the_type_it_was_given(connector, table):
    columns = ["whole", "ratio", "flag", "words", "untyped"]
    types = {
        "whole": ColumnType.INTEGER,
        "ratio": ColumnType.REAL,
        "flag": ColumnType.BOOLEAN,
        "words": ColumnType.TEXT,
    }

    connector.write(
        table, columns, [(7, 0.5, True, "né", "free")], mode=WriteMode.APPEND, types=types
    )

    name = connector.dialect.identifier(table)
    (row,) = connector.read(f"SELECT * FROM {name}")
    assert (row["whole"], row["ratio"], bool(row["flag"]), row["words"], row["untyped"]) == (
        7,
        0.5,
        True,
        "né",
        "free",
    )


@pytest.mark.parametrize("name", ["labels; DROP TABLE topics", 'la"bels', "la`bels", "", "a..b"])
def test_a_name_that_is_not_an_identifier_is_refused(connector, name):
    with pytest.raises(ConfigurationError, match="not a table or column name"):
        _write(connector, name, [(1, "a")])


def test_the_values_a_database_returns_have_a_json_form(connector):
    kind = connector.kind
    if kind == "sqlite":
        pytest.skip("SQLite returns only numbers, text and bytes")
    query = (
        "SELECT CAST('10.50' AS DECIMAL(10, 2)) AS price, "
        "CAST('2026-11-23' AS DATE) AS day, "
        "CAST('2026-11-23 08:30:00' AS {stamp}) AS at"
    ).format(stamp="DATETIME" if kind == "mysql" else "TIMESTAMP")

    (row,) = connector.read(query)

    assert isinstance(row["price"], decimal.Decimal) and isinstance(row["day"], datetime.date)
    assert {name: json_safe(value) for name, value in row.items()} == {
        "price": "10.50",
        "day": "2026-11-23",
        "at": "2026-11-23T08:30:00",
    }


EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "question_rounds"
WORKFLOW = "question_rounds"
FILE_SOURCE = """    type: local
    folder: ./staging
    file_type: [json]"""


def test_a_workflow_runs_from_a_query_to_a_table_on_this_database(settings, tmp_path, table):
    project = tmp_path / WORKFLOW
    shutil.copytree(EXAMPLE, project)
    _declare(project, settings)
    topics, published = f"topics_{table}", f"published_{table}"
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    source = (
        "    type: database\n    connection: warehouse\n"
        f"    sql: SELECT id, topic, bar FROM {topics}"
    )
    outputs = (
        f"\noutputs:\n  - action: publish\n    connection: warehouse\n"
        f"    table: {published}\n    carry: [id]\n    key: [id]\n"
    )
    text = config.read_text(encoding="utf-8")
    assert FILE_SOURCE in text
    config.write_text(text.replace(FILE_SOURCE, source) + outputs, encoding="utf-8")
    rows = [(1, "photosynthesis", 1), (2, "plate tectonics", 2), (3, "the water cycle", 9)]
    kinds = {"id": ColumnType.INTEGER, "topic": ColumnType.TEXT, "bar": ColumnType.INTEGER}
    with open_connection("warehouse", project) as seeded:
        seeded.write(topics, ["id", "topic", "bar"], rows, mode=WriteMode.APPEND, types=kinds)

    for _ in range(2):
        result = run_agac(project, "run", "-a", WORKFLOW, "--refresh-input")
        output = " ".join((result.stdout + result.stderr).split())
        assert result.returncode == 0, output[-3000:]

    with open_connection("warehouse", project) as read_back:
        held = sorted(
            (row["id"], row["status"], row["summary"])
            for row in read_back.read(f"SELECT id, status, summary FROM {published}")
        )
    assert held == [
        (1, "published", "photosynthesis: passed in round 1"),
        (2, "published", "plate tectonics: passed in round 2"),
    ]


def test_a_query_returning_a_column_name_twice_is_refused(connector):
    with pytest.raises(ConfigurationError, match="returns id more than once; give each column"):
        list(connector.read("SELECT 1 AS id, 2 AS id"))


def test_an_append_with_a_key_adds_only_the_rows_the_table_does_not_hold(connector, table):
    _write(connector, table, [(1, "a"), (2, "b")], mode=WriteMode.APPEND, key=["id"])

    assert _write(connector, table, [(2, "b"), (3, "c")], mode=WriteMode.APPEND, key=["id"]) == 1
    assert _held(connector, table) == [(1, "a"), (2, "b"), (3, "c")]


def test_a_merge_larger_than_one_statement_on_two_columns_replaces_each_row(connector, table):
    rows = [(n, f"row {n}") for n in range(1200)]
    _write(connector, table, rows, mode=WriteMode.MERGE, key=COLUMNS)
    _write(connector, table, rows, mode=WriteMode.MERGE, key=COLUMNS)

    assert _held(connector, table) == sorted(rows)
