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
`.env`). A credential **must** be written that way: a credential typed into the
project file is refused, and its value is kept out of the logs. The credentials
are `password`, `private_key_file_pwd` and `access_token`, and any setting
whose name holds `password`, `pwd`, `token`, `secret` or `passphrase`.

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
| `bigquery`, `databricks` | No | Rows are added by a load job on `bigquery`. A write that stops partway is put right by writing again |

`snowflake` names are quoted in upper case, the name Snowflake gives an
unquoted one, so a table made by hand is found and a column named like a
reserved word (`order`, `group`) still works. A result column in upper case is
read back in lower case, so a prompt reads `{{ source.title }}`.

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
| `files` | `1` | How many snapshot files the rows are spread over, at most 256. With one file the query's `ORDER BY` is kept, and an action with `granularity: File` sees every row at once. With more, each row goes to the file its content picks, and a File-granularity action runs once a file |

Every column of a row is a field of `source`, so a prompt reads `{{ source.title }}`.

### The query

The `sql` must read: it has to start with `SELECT`, `WITH` or `VALUES`, and
anything else (`DELETE`, `UPDATE`, `DROP`) is refused before it reaches the
database. SQLite and DuckDB are opened read-only for it, and Postgres and MySQL
get a read-only session, so a `WITH ... DELETE` cannot write either.

It must return rows, and each column must have a name of its own:
`SELECT t.id, u.id` is refused, so alias one with `AS`.

### The snapshot

The rows are written to `agent_io/_remote_cache/database/` the first time the
workflow runs, and every later run reads that snapshot. A run that pauses for a
batch and resumes a day later therefore sees the rows it started with.

Each start action keeps one snapshot. It belongs to the query, the file count
and the connection's settings (a `${NAME}` setting by the value it reads, a
credential by its name). Changing any of them reads the query again, and so
does going back to an earlier query: only the current one is kept.

To read the query again:

```bash
agac run -a my_workflow --refresh-input
```

The new rows replace the snapshot only once they are all read, so a refresh
that fails leaves the snapshot there was. `--refresh-input` is refused, before
anything else happens, while a batch is still open, since the batch answers the
rows it was sent.

A record's identity is its content, so after a refresh:

- a row that is unchanged keeps its answers and is not sent to a model again;
- a row that is new, or has any column changed, is answered;
- a row the query no longer returns is forgotten.

Dates, timestamps and decimals are stored as text (`2026-11-23`, `10.50`) and
binary values as base64. A timestamp with a time zone is stored in UTC, so a
row reads the same whichever zone the machine or the session is in. Cast a column in the query if it has a type that has
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
| `key` | `[source_guid]` | The columns that identify a row, for `merge` and `append` |
| `carry` | `[]` | Source fields to write beside the action's own |

Each record the action answered becomes one row: `source_guid`, the carried
source fields, then the action's output fields. A field holding a list or an
object is written as JSON text. A record the action did not answer (guard-skipped,
or failed above it) makes no row.

A table the export creates takes each column's type from the values written
that time: a column of whole numbers is an integer column. A field that no
answer carried yet (an optional one) is added as a column the first time an
answer carries it; the rows written before hold null in it. A name is matched
without regard to case, except on Postgres, where a quoted name keeps its case.
On MySQL, text columns are `LONGTEXT`, so a long body or answer fits. A later write of a
fraction to it is held as the database holds a fraction in an integer column
(SQLite keeps it; most databases round or refuse it). Create the table yourself
when a column's type must not depend on the first rows.

A carried field that no answered record's source holds is refused, since it is
more often a misspelling than a column of nulls.

### Modes

| Mode | What the table holds afterwards |
|------|---------------------------------|
| `append` | What it held, plus each row whose `key` it does not hold yet. Writing twice changes nothing; a source row that changed is added beside the old one. |
| `replace` | Exactly the rows the store holds now. |
| `merge` | What it held, with each row sharing a `key` replaced. Writing twice changes nothing. |

A key is compared as text, so it matches whatever type its column holds: an id
stored as `VARCHAR` matches the number `7`, and a Postgres `UUID` column matches
the `source_guid` text. Keep keys to ids and text; a timestamp or a fraction may
not read back as the same text.

`merge` and `append` refuse a row with no value for its key, before anything is
written. `merge` never removes a row. With the default key, a source row that changes
gets a new `source_guid`, so the table keeps both versions. Set `key` to the
row's own identifier (carried from the source) to have the new version replace
the old one, or use `replace` to mirror the store.

### When tables are written

The outputs are checked before any action runs: an output naming an action the
workflow does not run, or a connection the project does not declare, stops the
run at once. Tables are written when `agac run` or `agac retry` finishes with
every action complete. If the write fails, the results are still in the store. Write them
again, without calling a model, with:

```bash
agac export -w my_workflow
agac export -w my_workflow -A classify_ticket    # one action's table
```

`-A` must name an action that has an output.
