---
title: dispositions Command
description: Inspect record-level processing dispositions per action
sidebar_position: 8
---

# dispositions Command

The `dispositions` command shows, per action, what happened to every record a workflow processed — read from the `record_disposition` table in the durable store. Use it to see at a glance where records succeeded, failed, or fell out of the stream, before reaching for [`retry`](./retry).

```bash
agac dispositions -a <workflow-name> [options]
```

## Options

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Agent configuration file name without path or extension (required) |
| `--action TEXT` | Show dispositions for a specific action only |
| `--quarantined` | Show only failed/exhausted/unprocessed records, with details |

## Output

One row per action, with a count per disposition:

```
                              Dispositions: my_workflow
┃ Action  ┃ Success ┃ Failed checks ┃ Failed ┃ Exhausted ┃ Guard skipped ┃ Unprocessed ┃ Passthrough ┃ Filtered ┃ Total ┃ Records ┃
│ extract │      25 │             0 │      0 │         0 │             0 │           0 │           0 │        0 │    25 │      25 │
│ rewrite │       4 │             0 │      0 │         0 │            21 │           0 │           0 │        0 │    25 │      25 │
│ split   │       1 │             0 │      0 │         0 │             0 │           0 │           0 │        0 │     1 │       5 │
```

The table is printed at its full width. In a terminal narrower than that, its lines wrap
instead of cutting a count or an action name short.

| Disposition | Meaning |
|-------------|---------|
| **Success** | The record was processed by the action |
| **Failed checks** | The record was processed and shipped with a failing [expectations](../validation/expectations.md) verdict, as `on_exhausted: return_last` and `repair: none` ship it. Stored as `success` with reason `expectations_failed`: it is not a failure, nothing reading it is blocked, and `agac retry` does not re-run it. Counted apart from **Success** so the columns still add up to **Total** |
| **Failed** | Processing failed for the record |
| **Exhausted** | The record failed and its retries are used up |
| **Guard skipped** | The action's guard skipped the record and it flows on unchanged. Stored as `unprocessed` (see below) |
| **Unprocessed** | The action never answered the record for any other reason, such as an upstream failure that cascaded |
| **Passthrough** | The model or tool answered nothing and `on_empty: skip` kept the record as a tombstone |
| **Filtered** | The action removed the record from the stream |

A guard skip is stored as `unprocessed` in both run modes, with reason `guard_skip`, or
`guard_prefilter_skip` for an action of `granularity: file` (`guard_filter` on the rare
unprocessed row a batch path writes with no reason of its own): unprocessed keeps the record
open, so once the guard passes it again it is sent to the model, where a terminal
disposition would carry the tombstone for good. The summary counts those rows under
**Guard skipped** and the rest of the unprocessed rows under **Unprocessed**, so the columns
still add up to **Total**. `--quarantined` lists guard skips with their reason, as before.

### Why Total and Records can differ

**A disposition names the record it accounts for.** `Total` counts those rows;
`Records` counts the records currently stored under the action. They match for an
action that turns one record into one record, and they legitimately differ
otherwise.

An action that folds records together shows more dispositions than records:
every input it consumed is accounted for even though only one output carries
them, and those it consumed without leaving a row of their own say so with
`reason=consumed_into_output`. A FILE action that fans out also shows more, since
the rows it minted an identity for are accounted beside the inputs that produced
them. Neither case is data loss.

This is also why [`retry`](./retry)
targets inputs: retrying a record means re-running the input that failed.

`Records` counts every record stored under the action, which is not the same as
the records it successfully produced. A record that was guard-skipped, cascade-
skipped or failed is kept in the action's output as a placeholder so downstream
actions can still see it, and those placeholders are counted here. The `rewrite`
row above shows this: 4 successes and 21 guard skips, `Records 25`. The run line says the
same: `✓ rewrite  25 records in 1.2s — 21 skipped by guard`. So a high
`Records` is not on its own evidence that the action worked — read it against
the `Failed`, `Guard skipped`, `Unprocessed` and `Passthrough` columns, or use `--quarantined` for
the detail.

`Records` also reads what is in the store *now*, not only this run's output.
Re-running a workflow over differently named input files leaves the earlier
run's records in place and counts them too; `agac run --fresh` clears them. A
`?` means the count could not be read at all — which is not the same as zero.

## Examples

### Full workflow overview

```bash
agac dispositions -a my_workflow
```

### One action only

```bash
agac dispositions -a my_workflow --action extract_facts
```

### Inspect stuck records

`--quarantined` lists each failed, exhausted, or unprocessed record — action, record ID, disposition, and reason — so you can decide what to [`retry`](./retry):

```bash
agac dispositions -a my_workflow --quarantined
```

`retry` acts on the failed and exhausted ones. An unprocessed record is listed with the
reason no answer reached it — an upstream failure (`upstream_unprocessed`), a guard skip
(`guard_skip`), a record a `granularity: File` tool left out (`tool_missing_record`) or
folded into another record's row (`consumed_into_another_record`) — which tells you
where to look instead.

When nothing is stuck it reports `No quarantined records found.`

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::
