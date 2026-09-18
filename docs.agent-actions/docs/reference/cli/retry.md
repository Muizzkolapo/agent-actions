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

## Record limits never exclude a retried record

A record limit — [`record_limit`](../configuration/defaults) or
[`AGAC_MAX_RECORDS`](../configuration/) — keeps the first N records of an input
file. `retry` selects records by id, so the records it is repairing are admitted
on top of that N rather than cut loose by it.

A retry takes on no work the limit was holding back: it adds the records it was
asked to repair, and nothing else.

This matters because `retry` clears a record's disposition before re-running it.
A retry that skipped the record would not leave it failed — it would leave no
record of the failure at all.

Two limits of the current behaviour:

- `file_limit` is not covered. A retry still stops at N input files, so a record
  in a later file is not reached.
- An action that turns one record into several gives the new records fresh
  identifiers, so a retry's ids do not match them at actions below that point.
  `retry` already clears dispositions by the same ids, so this is not new.

A capped retry also rewrites an action's output with only the records it
processed, so records it did not name lose their stored rows while keeping their
`success` dispositions. That predates this behaviour and is unchanged by it.

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::
