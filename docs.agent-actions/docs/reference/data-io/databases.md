---
title: Databases
sidebar_position: 6
---

# Databases

A workflow can read its input rows from a database and write its results to a
table, instead of reading files from `staging/` and leaving results in the store.

The store stays where the work is kept. A query is read once, before the first
action; a table is written once, after the last.

## Connections

Name each database in `agent_actions.yml`:

```yaml
connections:
  warehouse:
    type: postgres
    host: db.internal
    dbname: analytics
    user: loader
    password: ${WAREHOUSE_PASSWORD}
```

A connection is opened only when a workflow uses it.

### Secrets

Any setting can be written as `${NAME}` to read it from the environment (or
`.env`). A setting whose name holds `password`, `token`, `secret` or
`passphrase` **must** be written that way: a credential typed into the project
file is refused, and its value is kept out of the logs.

### Types

Each type but `sqlite` needs its driver, installed as an extra of the same name:

```bash
pip install 'agent-actions[postgres]'
```

| Type | Driver | Settings (required in bold) |
|------|--------|-----------------------------|
| `sqlite` | built in | **`path`** |
| `duckdb` | `duckdb` | **`path`** |
| `postgres` | `psycopg` | **`host`**, **`dbname`**, **`user`**, `password`, `port`, `sslmode`, `connect_timeout` |
| `mysql` | `pymysql` | **`database`**, **`user`**, `password`, `host`, `port`, `unix_socket`, `connect_timeout` |
| `redshift` | `redshift-connector` | **`host`**, **`database`**, `user`, `password`, `port`, `iam`, `cluster_identifier`, `region`, `db_user`, `sslmode` |
| `snowflake` | `snowflake-connector-python` | **`account`**, **`user`**, `password`, `private_key_file`, `private_key_file_pwd`, `authenticator`, `warehouse`, `database`, `schema`, `role` |
| `bigquery` | `google-cloud-bigquery` | **`project`**, `dataset`, `location`, `keyfile` |
| `databricks` | `databricks-sql-connector` | **`server_hostname`**, **`http_path`**, **`access_token`**, `catalog`, `schema` |

A `path` or `keyfile` is relative to the project. `bigquery` without a
`keyfile` uses the environment's own Google credentials; `redshift` with
`iam: true` uses the environment's AWS credentials.

### What differs between types

| Type | A write is one transaction | Notes |
|------|----------------------------|-------|
| `sqlite`, `duckdb`, `postgres`, `redshift` | Yes, table creation included | |
| `mysql`, `snowflake` | Rows yes; a `CREATE TABLE` commits at once | A first write that fails leaves the new table behind, empty |
| `bigquery`, `databricks` | No | Rows are added by a load job on `bigquery`. A write that stops partway is put right by writing again, except an `append` |

`snowflake` names are written unquoted, so Snowflake folds them to upper case
as it does for a table made by hand; a result column it folded is read back in
lower case, so a prompt reads `{{ source.title }}`.

:::note How each type is tested
`sqlite`, `duckdb`, `postgres` and `mysql` are run against a real database by
the test suite. `redshift`, `snowflake`, `bigquery` and `databricks` share the
same code and are tested against a stand-in for their driver: the statements
they send are checked, but not against a live account.
:::

## Reading input

Point the workflow's `data_source` at a connection and a query:

```yaml
defaults:
  data_source:
    type: database
    connection: warehouse
    sql: SELECT id, title, body FROM tickets WHERE created_at >= '2026-11-01'
```

| Key | Default | Meaning |
|-----|---------|---------|
| `connection` | required | A name from the project's `connections:` block |
| `sql` | required | The query to read; each row becomes one record |
| `files` | `8` | How many snapshot files the rows are spread over |

Every column of a row is a field of `source`, so a prompt reads `{{ source.title }}`.

### The snapshot

The rows are written to `agent_io/_remote_cache/database/` the first time the
workflow runs, and every later run reads that snapshot. A run that pauses for a
batch and resumes a day later therefore sees the rows it started with.

To read the query again:

```bash
agac run -a my_workflow --refresh-input
```

A record's identity is its content, so after a refresh:

- a row that is unchanged keeps its answers and is not sent to a model again;
- a row that is new, or has any column changed, is answered;
- a row the query no longer returns is forgotten.

Dates, timestamps and decimals are stored as text (`2026-11-23`, `10.50`) and
binary values as base64. Cast a column in the query if it has a type that has
no JSON form.

## Writing results

Declare the tables at the top level of the workflow:

```yaml
outputs:
  - action: classify_ticket
    connection: warehouse
    table: ticket_classification
    carry: [id]
    key: [id]
```

| Key | Default | Meaning |
|-----|---------|---------|
| `action` | required | The action whose records are written |
| `connection` | required | A name from the project's `connections:` block |
| `table` | required | The table to write; created when it does not exist |
| `mode` | `merge` | `append`, `replace` or `merge` |
| `key` | `[source_guid]` | The columns that identify a row, for `merge` |
| `carry` | `[]` | Source fields to write beside the action's own |

Each record the action answered becomes one row: `source_guid`, the carried
source fields, then the action's output fields. A field holding a list or an
object is written as JSON text. A record the action did not answer (guard-skipped,
or failed above it) makes no row.

### Modes

| Mode | What the table holds afterwards |
|------|---------------------------------|
| `append` | What it held, plus every row written. Writing twice doubles the rows. |
| `replace` | Exactly the rows the store holds now. |
| `merge` | What it held, with each row sharing a `key` replaced. Writing twice changes nothing. |

`merge` never removes a row, and refuses a row with no value for its key. With the default key, a source row that changes
gets a new `source_guid`, so the table keeps both versions. Set `key` to the
row's own identifier (carried from the source) to have the new version replace
the old one, or use `replace` to mirror the store.

### When tables are written

Tables are written when `agac run` finishes with every action complete. If the
write fails, the results are still in the store. Write them again, without
calling a model, with:

```bash
agac export -w my_workflow
agac export -w my_workflow -A classify_ticket    # one action's table
```
