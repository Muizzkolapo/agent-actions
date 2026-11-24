# Ticket triage from a warehouse

Support tickets are read from a database table, classified, routed to a team,
and counted, and the results are written back to the same database as three
tables. Nothing is staged as files: the workflow's `data_source` is a query.

It runs offline: the workflow uses the `agac-provider` mock vendor, and the
warehouse is a SQLite file. Point the `warehouse` connection in
`agent_actions.yml` at Postgres, Snowflake, BigQuery or another type to use a
real one (see [Databases](https://docs.runagac.com/docs/reference/data-io/databases)).

## What it shows

| Piece | Where | What it does |
|---|---|---|
| `connections:` | `agent_actions.yml` | Names the database once; the workflow refers to it as `warehouse`. |
| `data_source: {type: database}` | workflow `defaults` | Reads `SELECT ticket_id, subject, body FROM tickets` once into a snapshot; each row is a record. |
| `classify` | LLM action | Category, urgency and a one-line summary per ticket. |
| `route` | tool | A team and an SLA per ticket; a refund request adds the optional `escalation` field. |
| `digest` | tool, `granularity: File` | One row counting the tickets each team received. |
| `outputs:` | workflow | `route` → `ticket_routing` (merge on `ticket_id`), `classify` → `triage_log` (append), `digest` → `routing_digest` (replace). |

## Run it

```bash
python seed_warehouse.py
agac run -a ticket_triage_warehouse
sqlite3 warehouse.db "SELECT ticket_id, team, sla_hours FROM ticket_routing"
```

Then change the source and read it again. Only the new and changed tickets are
sent to the model; the rest keep their answers:

```bash
sqlite3 warehouse.db "INSERT INTO tickets VALUES (6, 'Refund', 'I want a refund')"
agac run -a ticket_triage_warehouse --refresh-input
sqlite3 warehouse.db "SELECT ticket_id, team, escalation FROM ticket_routing"
```

`ticket_routing` gains an `escalation` column the first time a ticket needs
one, and `routing_digest` still holds one row, now counting six tickets. If a
write fails, the answers are kept in the store: `agac export -w
ticket_triage_warehouse` writes the tables again without calling a model.
