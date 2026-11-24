# Database input and output

A workflow can read its input rows from a database and write an action's results to a
table. The store (`agent_io/store/<workflow>.db`) stays where the work is kept: the query
is read once before the first action, and the tables are written once after the last.

Full reference: `docs.agent-actions/docs/reference/data-io/databases.md`.

## Connections (`agent_actions.yml`)

```yaml
connections:
  warehouse:
    type: postgres            # sqlite, duckdb, postgres, mysql, redshift, snowflake, bigquery, databricks
    host: db.internal
    dbname: analytics
    user: loader
    password: ${WAREHOUSE_PASSWORD}
```

- Every type but `sqlite` needs its extra: `pip install 'agent-actions[postgres]'`.
- A credential (`password`, `private_key_file_pwd`, `access_token`, or any setting whose
  name holds `password`, `pwd`, `token`, `secret` or `passphrase`) **must** be `${NAME}`;
  a literal one is refused. Put the value in `.env`.
- `path` and `keyfile` are relative to the project.

## Reading input

```yaml
defaults:
  data_source:
    type: database
    connection: warehouse
    sql: SELECT id, title, body FROM tickets WHERE status = 'open'
```

- Each row is one record; each column is a field of `source` (`{{ source.title }}`).
- The `sql` must start with `SELECT`, `WITH`, `VALUES` or `TABLE`. Each column needs its
  own name: alias a repeated one with `AS`.
- The rows are kept in a snapshot (`agent_io/_remote_cache/database/`). Later runs, and a
  resume after a batch, read the snapshot, not the database. A change to the query, the
  connection settings or `files` reads it again.
- `agac run -w <workflow> --refresh-input` reads the query again. Unchanged rows keep their
  answers; new or changed rows are answered; rows no longer returned are forgotten. It is
  refused while a batch is open.
- `files` (default `1`) spreads rows over several snapshot files. Keep `1` when an action
  has `granularity: File` and must see every row, or when the query's `ORDER BY` matters.

## Writing results

```yaml
outputs:                      # top level of the workflow, beside `actions:`
  - action: classify_ticket
    connection: warehouse
    table: ticket_classification
    mode: merge               # append | replace | merge (default merge)
    carry: [id]               # source fields written beside the action's own
    key: [id]                 # default [source_guid]
```

- One row per record the action answered: `source_guid`, the carried fields, then the
  action's output fields. Lists and objects are written as JSON text. A filtered or failed
  record makes no row.
- `merge`: rows sharing a `key` are replaced. `append`: rows whose `key` the table holds
  are skipped. `replace`: the table holds exactly the stored rows.
- With the default key, a changed source row gets a new `source_guid`, so `merge` keeps
  both versions. Carry the row's own id and set `key: [id]` to replace the old version.
- The table is created when absent; a field that appears later is added as a column.
- Tables are written when `agac run` or `agac retry` finishes with every action complete.
  `agac export -w <workflow>` writes them again without calling a model; `-A <action>`
  writes one action's table.

## Common mistakes

| Symptom | Cause | Fix |
|---------|-------|-----|
| "No connection named ..." | The name is not under `connections:` | Add it, or fix the spelling |
| A secret "written in the project file" | A literal password or token | Use `${NAME}` and put the value in `.env` |
| A carried field "no answered record's source holds" | Misspelt `carry` entry | Use the column name the query returns |
| Old rows answered again after editing the query | The snapshot belongs to the query | Expected; only rows whose content changed cost a model call |
| `--refresh-input` refused | A batch is still open | `agac run --wait`, then refresh |
