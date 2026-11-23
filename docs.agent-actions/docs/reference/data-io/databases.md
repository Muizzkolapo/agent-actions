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
    type: sqlite
    path: data/warehouse.db    # relative to the project
```

`sqlite` is the one type that ships. A connection is opened only when a workflow
uses it.

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

`merge` never removes a row. With the default key, a source row that changes
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
