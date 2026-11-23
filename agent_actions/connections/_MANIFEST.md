# Connections Manifest

## Overview

Named database connections a workflow reads its input rows from and writes its
results to. The store stays the system of record: a query is read once into
staging documents before the first action, and a table is written from the
store after the last.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | `CONNECTORS` registry (type name to `module:Class`, imported when a project names the type) and `open_connection(name, project_root)`, which reads the project's `connections:` block. | `config.path_config`, `errors` |
| `base.py` | Module | `Connector` contract (`from_settings`, `check`, `read`, `write`, `close`), `WriteMode` (`append`, `replace`, `merge`), `ColumnType` (the type a created column is given), `quoted_identifier` (a table or column name is validated, then quoted) and `json_safe` (a database value's one JSON form, so a row read twice has one identity). | `errors` |
| `settings.py` | Module | `read_settings` validates one connection's settings against its model, reads each `${NAME}` value from the environment, refuses a secret written in the project file, and registers a secret's value with the log redaction. A setting is a secret when its settings model marks it (`json_schema_extra={"secret": True}`) or its name holds `password`, `pwd`, `token`, `secret` or `passphrase`. | `pydantic`, `logging.filters`, `errors` |
| `dbapi.py` | Module | `DbApiConnector`: `read` and `write` over any PEP 249 driver, and `Dialect` (parameter style, identifier quote, column type names). A database's connector adds how to connect and the hooks it needs (`_begin`, `_commit`, `_cursor`, `_read_cursor`, `_insert`, `_column_name`). A write probes the table with a zero-row select, creates it when absent, then deletes and inserts in one transaction where the database has them. | `connections.base`, `errors` |
| `sqlite.py` | Module | `SqliteConnector`, on the standard library; an untyped column is declared with no type. | `sqlite3` |
| `duckdb.py` | Module | `DuckdbConnector`; statements run on the connection itself, since a DuckDB cursor is another connection outside its transaction. | `duckdb` |
| `postgres.py` | Module | `PostgresConnector` through psycopg; a query is read through a server-side cursor. | `psycopg` |
| `mysql.py` | Module | `MysqlConnector` through PyMySQL; a query is read unbuffered. | `pymysql` |
| `redshift.py` | Module | `RedshiftConnector` through `redshift_connector`, with password or IAM sign-in. | `redshift_connector` |
| `snowflake.py` | Module | `SnowflakeConnector`; names are written bare and a folded result column is read back in lower case. | `snowflake.connector` |
| `bigquery.py` | Module | `BigqueryConnector`; rows are added by a load job into the full table id. | `google.cloud.bigquery` |
| `databricks.py` | Module | `DatabricksConnector`; named parameters, and nothing to commit. | `databricks.sql` |
| `export.py` | Module | `output_table` turns an action's stored records into columns and rows (identity, carried source fields, the action's own fields; nested values as JSON text; a record the action did not answer makes no row; a carried field no answered record's source holds is refused). `column_types` gives each column the type its values share. `write_output` / `write_outputs` write the outputs a workflow declares, refusing one that names an action the workflow does not run; an output with no answered rows writes nothing (a replace empties its table) before its key is checked; a merge keeps the last stored row of each key. | `storage.backend`, `record.state`, `config.schema` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `open_connection()` | `agent_actions.yml` | Reads | `connections` |
| `write_outputs()` | `agent_config/{workflow}.yml` | Reads | `outputs` |
| `write_outputs()` | `agent_io/store/` | Reads | — |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | Project config holds the `connections:` block; `OutputConfig` models an `outputs:` entry |
| `storage` | outbound | An export reads an action's records from the store |
| `record` | outbound | The record states that make no output row |
| `input` | inbound | A `database` data source snapshots a query through a connector |
| `cli` | inbound | `agac run` writes declared outputs once a run finishes; `agac export` repeats it |

## Notes

- A new type is one more `CONNECTORS` entry, a `DbApiConnector` subclass and an extra in
  `pyproject.toml` named as the type; its driver is imported only when a connection opens.
- `sqlite`, `duckdb`, `postgres` and `mysql` are held to one contract against a real database
  (`tests/integration/test_every_connection_type_reads_and_writes_alike.py`); the types that
  need an account are tested against a stand-in driver.
