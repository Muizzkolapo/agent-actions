"""The connection types that need an account, run against a stand-in for their driver.

They share the code path the live databases exercise, so what is checked here is
only what differs: what each hands its driver to connect, and the statements it
sends. None of this proves a real warehouse accepts them.
"""

import sys
import types
from pathlib import Path

import pytest

from agent_actions.connections import ColumnType, WriteMode, open_connection
from agent_actions.errors import ConfigurationError

COLUMNS = ["id", "label"]
TYPES = {"id": ColumnType.INTEGER}


class _Cursor:
    def __init__(self, log: list) -> None:
        self._log = log
        self.description = [("ID",), ("LABEL",)]
        self._rows: list[tuple] = []

    def execute(self, statement, parameters=None):
        self._log.append((statement, parameters))
        if "WHERE 1 = 0" in statement:
            raise LookupError("no such table")
        if statement.startswith("SELECT"):
            self._rows = [(1, "a")]

    def executemany(self, statement, parameters):
        self._log.append((statement, list(parameters)))

    def fetchmany(self, size):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        pass


class _Connection:
    def __init__(self, log: list) -> None:
        self.log = log

    def cursor(self, *args, **kwargs):
        return _Cursor(self.log)

    def commit(self):
        self.log.append(("COMMIT", None))

    def rollback(self):
        pass

    def close(self):
        pass


class _Driver:
    """Records how it was asked to connect and every statement sent after."""

    def __init__(self) -> None:
        self.connected_with: dict = {}
        self.log: list = []
        self.loaded: list = []

    def connect(self, *args, **options):
        self.connected_with = {"args": args, **options}
        return _Connection(self.log)

    @property
    def statements(self) -> list[str]:
        return [statement for statement, _ in self.log]


def _module(name: str, **members) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in members.items():
        setattr(module, key, value)
    return module


@pytest.fixture
def driver(monkeypatch) -> _Driver:
    driver = _Driver()

    class _Client:
        def __init__(self, **options) -> None:
            driver.connected_with = options

        def load_table_from_json(self, records, table):
            driver.loaded.append((table, records))
            return types.SimpleNamespace(result=lambda: None)

    bigquery = _module(
        "google.cloud.bigquery",
        Client=_Client,
        QueryJobConfig=lambda **options: options,
        dbapi=_module(
            "google.cloud.bigquery.dbapi", connect=lambda client: _Connection(driver.log)
        ),
    )
    stand_ins = {
        "redshift_connector": _module("redshift_connector", connect=driver.connect),
        "snowflake": _module("snowflake"),
        "snowflake.connector": _module("snowflake.connector", connect=driver.connect),
        "databricks": _module("databricks", sql=_module("databricks.sql", connect=driver.connect)),
        "databricks.sql": _module("databricks.sql", connect=driver.connect),
        "google": _module("google"),
        "google.cloud": _module("google.cloud", bigquery=bigquery),
        "google.cloud.bigquery": bigquery,
        "google.cloud.bigquery.dbapi": bigquery.dbapi,
    }
    stand_ins["snowflake"].connector = stand_ins["snowflake.connector"]
    for name, module in stand_ins.items():
        monkeypatch.setitem(sys.modules, name, module)
    return driver


SETTINGS = {
    "redshift": "host: rs.example\n    database: dev\n    user: loader\n    password: ${PW}",
    "snowflake": "account: acme\n    user: loader\n    password: ${PW}\n    schema: PUBLIC",
    "databricks": "server_hostname: dbx.example\n    http_path: /sql/1\n    access_token: ${PW}",
    "bigquery": "project: acme\n    dataset: analytics\n    location: EU",
}


def _open(kind: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PW", "s3cret-value")
    (tmp_path / "agent_actions.yml").write_text(
        f"connections:\n  warehouse:\n    type: {kind}\n    {SETTINGS[kind]}\n", encoding="utf-8"
    )
    return open_connection("warehouse", tmp_path)


@pytest.mark.parametrize(
    ("kind", "handed"),
    [
        (
            "redshift",
            {"host": "rs.example", "port": 5439, "database": "dev", "user": "loader", "iam": False},
        ),
        (
            "snowflake",
            {"account": "acme", "user": "loader", "schema": "PUBLIC", "autocommit": False},
        ),
        ("databricks", {"server_hostname": "dbx.example", "http_path": "/sql/1"}),
        (
            "bigquery",
            {
                "project": "acme",
                "location": "EU",
                "default_query_job_config": {"default_dataset": "acme.analytics"},
            },
        ),
    ],
)
def test_the_driver_is_handed_the_connection_s_settings(
    kind, handed, driver, tmp_path, monkeypatch
):
    with _open(kind, tmp_path, monkeypatch) as connector:
        connector.check()

    secret = {"redshift": "password", "snowflake": "password", "databricks": "access_token"}
    expected = {**handed, **({secret[kind]: "s3cret-value"} if kind in secret else {})}
    assert {key: driver.connected_with[key] for key in expected} == expected


@pytest.mark.parametrize(
    ("kind", "create", "delete", "insert"),
    [
        (
            "redshift",
            'CREATE TABLE IF NOT EXISTS "out"."labels" ("id" BIGINT, "label" VARCHAR(65535))',
            'DELETE FROM "out"."labels" WHERE "id" = %s',
            'INSERT INTO "out"."labels" ("id", "label") VALUES (%s, %s)',
        ),
        (
            "snowflake",
            "CREATE TABLE IF NOT EXISTS out.labels (id NUMBER(38, 0), label VARCHAR)",
            "DELETE FROM out.labels WHERE id = %s",
            "INSERT INTO out.labels (id, label) VALUES (%s, %s)",
        ),
        (
            "databricks",
            "CREATE TABLE IF NOT EXISTS `out`.`labels` (`id` BIGINT, `label` STRING)",
            "DELETE FROM `out`.`labels` WHERE `id` = :p0",
            "INSERT INTO `out`.`labels` (`id`, `label`) VALUES (:p0, :p1)",
        ),
    ],
)
def test_a_merge_is_sent_in_the_database_s_own_words(
    kind, create, delete, insert, driver, tmp_path, monkeypatch
):
    with _open(kind, tmp_path, monkeypatch) as connector:
        written = connector.write(
            "out.labels", COLUMNS, [(1, "a")], mode=WriteMode.MERGE, key=["id"], types=TYPES
        )

    assert written == 1
    assert driver.statements[1:] == [create, delete, insert] + (
        [] if kind == "databricks" else ["COMMIT"]
    )
    bound = driver.log[3][1]
    assert bound == ([{"p0": 1, "p1": "a"}] if kind == "databricks" else [(1, "a")])


def test_bigquery_adds_rows_by_a_load_job_into_the_full_table_name(driver, tmp_path, monkeypatch):
    with _open("bigquery", tmp_path, monkeypatch) as connector:
        connector.write("labels", COLUMNS, [(1, "a")], mode=WriteMode.REPLACE, types=TYPES)

    assert driver.statements[1:3] == [
        "CREATE TABLE IF NOT EXISTS `labels` (`id` INT64, `label` STRING)",
        "DELETE FROM `labels` WHERE 1 = 1",
    ]
    assert driver.loaded == [("acme.analytics.labels", [{"id": 1, "label": "a"}])]


def test_a_column_snowflake_folded_to_upper_case_is_read_back_in_lower(
    driver, tmp_path, monkeypatch
):
    with _open("snowflake", tmp_path, monkeypatch) as connector:
        assert list(connector.read("SELECT id, label FROM labels")) == [{"id": 1, "label": "a"}]


@pytest.mark.parametrize("kind", sorted(SETTINGS))
def test_a_driver_that_is_not_installed_says_which_extra_to_install(kind, tmp_path, monkeypatch):
    for name in ("redshift_connector", "snowflake", "databricks", "google.cloud.bigquery"):
        monkeypatch.setitem(sys.modules, name, None)

    with _open(kind, tmp_path, monkeypatch) as connector:
        with pytest.raises(ConfigurationError, match=rf"pip install 'agent-actions\[{kind}\]'"):
            connector.check()
