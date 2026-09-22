---
title: retry Command
description: Retry failed or exhausted records from a specific action forward
sidebar_position: 9
---

# retry Command

The `retry` command re-runs failed or exhausted records from an action forward, instead of re-running the whole workflow. Use [`dispositions`](./dispositions) first to see what is stuck and where.

```bash
agac retry -a <workflow-name> [options]
```

## Options

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Agent configuration file name without path or extension (required) |
| `--from TEXT` | Action to retry from. If omitted, retries from the earliest failure |
| `--record TEXT` | Restrict retry to a single record (by `source_guid`) at the `--from` action |
| `--dry-run` | Show what would be retried without executing |

## Examples

### See what would be retried

Always safe — nothing executes:

```bash
agac retry -a my_workflow --dry-run
```

When nothing is stuck it reports `No failed or exhausted records found. Nothing to retry.`

### Retry from the earliest failure

```bash
agac retry -a my_workflow
```

### Retry from a specific action

```bash
agac retry -a my_workflow --from extract_facts
```

### Retry a single record

```bash
agac retry -a my_workflow --from extract_facts --record 3f9a1c2e-...
```

`--record` takes the identifier shown in the **Record ID** column of [`dispositions --quarantined`](./dispositions) — retry matches against exactly that value.

## A retry runs the records it named, and only those

`retry` selects records by id — the ones that failed, or the single one given to
`--record`. Those are the records it processes at every action it re-runs, and
they are the only ones.

Nothing else in the input joins them. A record limit —
[`record_limit`](../configuration/defaults) or
[`AGAC_RECORD_LIMIT`](../configuration/) — keeps the first N records of an input
file, but deciding how much new work to take on is what a limit is for, and a
repair takes on none. A record the retry did not name is not work this run was
asked to do, however far inside the limit it sits.

[`file_limit`](../configuration/defaults) — and `--file-limit` or
`AGAC_FILE_LIMIT` — does not hold a retry back either. A retry resolves which
staged files hold the records it named and visits every one of them, instead of
walking the directory and stopping at N.

Being exempt from a limit is not being exempt from reading it. A value that
cannot be a limit at all — `AGAC_FILE_LIMIT=nonsense` — still fails a retry
while the workflow is assembled, as it fails any other command. An empty
variable is not such a value; it reads as unset.

Records the retry did not name keep what they already had. Their stored output
rows are carried into the rewritten file, and their dispositions are left alone —
a record that failed at an action the retry re-runs is still failed afterwards
unless the retry named it too.

This matters because `retry` clears a record's disposition before re-running it.
A retry that never reached the record would not leave it failed — it would leave
no record of the failure at all.

An action that turns one record into several gives the new rows fresh
identifiers, so a retry's ids match none of them. Those rows are resolved back
to the record they came from instead. A row is rewritten when the retry named a
record that is an input of that action and the row either carries that record's
id or names it as its parent; every other row is carried. So repairing a record
whose row was split in two replaces both halves rather than adding two more
beside them.

One limit remains. A row carries the *original* staged record it descends from,
not the record that produced it directly, so where one such action feeds another
the rows of the second name a record that is no longer its input. They cannot be
attributed to anything the retry named, and are carried as they stand — the run
reports how many, and repairing one of that action's records leaves its previous
rows in the file beside the new ones.

Dispositions are cleared by the ids the retry was given, so an id that names no
input of an action is simply not found there — nothing at that action is
re-run, and nothing it holds is removed.

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::
