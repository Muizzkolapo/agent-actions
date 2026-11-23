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
| `sqlite.py` | Module | `SqliteConnector`: the reference connector, on the standard library. A write is one transaction, table creation included, and a write of no rows creates no table; `merge` deletes the rows sharing a key with an incoming row, then inserts. | `sqlite3`, `errors` |
| `export.py` | Module | `output_table` turns an action's stored records into columns and rows (identity, carried source fields, the action's own fields; nested values as JSON text; a record the action did not answer makes no row). `column_types` gives each column the type its values share. `write_output` / `write_outputs` write the outputs a workflow declares, refusing one that names an action the workflow does not run; a merge keeps the last stored row of each key. | `storage.backend`, `record.state`, `config.schema` |

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

- A warehouse connector (BigQuery, Snowflake) is one more `CONNECTORS` entry and a
  class meeting `Connector`; its driver is imported only when a project names the type.
- `write` takes rows in bulk so a connector can use its database's load path.
