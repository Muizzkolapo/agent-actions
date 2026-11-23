"""A connection is named in agent_actions.yml; its secrets come from the environment."""

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from agent_actions.connections import CONNECTORS, WriteMode, open_connection
from agent_actions.connections.settings import read_settings
from agent_actions.errors import ConfigurationError
from agent_actions.logging.filters import redact_known_secrets


class _Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 5432
    password: str | None = None


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

    with pytest.raises(ConfigurationError, match="type 'oracle'; the types are bigquery"):
        open_connection("warehouse", project)


def test_the_types_are_the_ones_documented():
    assert sorted(CONNECTORS) == [
        "bigquery",
        "databricks",
        "duckdb",
        "mysql",
        "postgres",
        "redshift",
        "snowflake",
        "sqlite",
    ]


def test_a_setting_written_as_a_reference_is_read_from_the_environment():
    settings = read_settings(
        "warehouse",
        {"type": "postgres", "host": "${DB_HOST}", "password": "${DB_PASSWORD}"},
        _Settings,
        environ={"DB_HOST": "db.internal", "DB_PASSWORD": "s3cret-value"},
    )

    assert (settings.host, settings.port, settings.password) == (
        "db.internal",
        5432,
        "s3cret-value",
    )


def test_a_secret_read_from_the_environment_is_kept_out_of_the_logs():
    read_settings(
        "warehouse",
        {"host": "db", "password": "${DB_PASSWORD}"},
        _Settings,
        environ={"DB_PASSWORD": "s3cret-value"},
    )

    assert "s3cret-value" not in redact_known_secrets("connecting with s3cret-value")


def test_a_secret_written_in_the_project_file_is_refused():
    with pytest.raises(ConfigurationError, match="'password' must name an environment variable"):
        read_settings("warehouse", {"host": "db", "password": "hunter2"}, _Settings)


def test_a_reference_to_a_variable_that_is_not_set_names_it():
    with pytest.raises(ConfigurationError, match="reads 'host' from DB_HOST, which is not set"):
        read_settings("warehouse", {"host": "${DB_HOST}"}, _Settings, environ={})


def test_a_setting_the_type_does_not_take_names_the_ones_it_does():
    with pytest.raises(ConfigurationError, match="hostname.*Its settings are host, password, port"):
        read_settings("warehouse", {"host": "db", "hostname": "db"}, _Settings)


def test_a_missing_setting_is_named():
    with pytest.raises(ConfigurationError, match="Connection 'warehouse' is not set up: host"):
        read_settings("warehouse", {}, _Settings)


def test_a_sqlite_column_given_no_type_holds_a_value_as_written(tmp_path: Path):
    project = _project(tmp_path, "connections:\n  warehouse:\n    type: sqlite\n    path: w.db\n")

    with open_connection("warehouse", project) as connector:
        connector.write("labels", ["id", "label"], [(1, "a")], mode=WriteMode.APPEND)

        assert list(connector.read("SELECT * FROM labels")) == [{"id": 1, "label": "a"}]
