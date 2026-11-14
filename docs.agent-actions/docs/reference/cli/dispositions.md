---
title: dispositions Command
description: Show the processing disposition of each record, for each action
sidebar_position: 8
---

# dispositions Command

The `dispositions` command shows, for each action, what occurred to each record that a workflow processed. The command reads the `record_disposition` table in the durable store. Use it to see quickly where records succeeded, failed or left the stream. Use it before you use [`retry`](./retry).

```bash
agac dispositions -a <workflow-name> [options]
```

## Options

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | The name of the agent configuration file, with no path or extension (required) |
| `--action TEXT` | Show the dispositions for only the specified action |
| `--quarantined` | Show only the failed, exhausted and unprocessed records, with details |

## Output

The output has one row for each action, with a count for each disposition:

```
                              Dispositions: my_workflow
┃ Action  ┃ Success ┃ Failed checks ┃ Failed ┃ Exhausted ┃ Guard skipped ┃ Unprocessed ┃ Passthrough ┃ Filtered ┃ Total ┃ Records ┃
│ extract │      25 │             0 │      0 │         0 │             0 │           0 │           0 │        0 │    25 │      25 │
│ rewrite │       4 │             0 │      0 │         0 │            21 │           0 │           0 │        0 │    25 │      25 │
│ split   │       1 │             0 │      0 │         0 │             0 │           0 │           0 │        0 │     1 │       5 │
```

The command prints the table at its full width. In a narrower terminal, the lines of the table wrap.
The command does not cut a count or an action name short.

| Disposition | Meaning |
|-------------|---------|
| **Success** | The action processed the record |
| **Failed checks** | The action processed the record and sent it on with a failing [expectations](../validation/expectations.md) verdict. `on_exhausted: return_last` and `repair: none` send the record on in this way. The store keeps it as `success` with reason `expectations_failed`. It is not a failure. Nothing that reads it is blocked, and `agac retry` does not run it again. The summary counts it separately from **Success**, so that the columns still add up to **Total** |
| **Failed** | The processing of the record failed |
| **Exhausted** | The record failed and no retries remain for it |
| **Guard skipped** | The guard of the action skipped the record, and the record continues downstream with no change. The store keeps it as `unprocessed` (see below) |
| **Unprocessed** | The action never answered the record, for any other reason. An example is an upstream failure that cascaded |
| **Passthrough** | The model or the tool gave no answer, and `on_empty: skip` kept the record as a tombstone |
| **Filtered** | The action removed the record from the stream |

In the two run modes, the store keeps a guard skip as `unprocessed`. The reason is `guard_skip`.
For an action of `granularity: file`, the reason is `guard_prefilter_skip`.
In rare cases, a batch path writes an unprocessed row with no reason of its own. That row gets the reason `guard_filter`.

The disposition `unprocessed` keeps the record open. Thus, when the guard lets the record pass again, the action sends it to the model.
A terminal disposition would keep the tombstone permanently.

The summary counts the guard skip rows under **Guard skipped**, and the other unprocessed rows under **Unprocessed**. Thus the columns still add up to **Total**.
`--quarantined` continues to list guard skips with their reason.

### Total and Records Can Differ {/* #why-total-and-records-can-differ */}

**A disposition names the record that it accounts for.** `Total` counts those rows.
`Records` counts the records that the store currently keeps under the action. For an
action that changes one record into one record, the two counts match. For other actions, the two counts can differ, and this difference is correct.

An action that merges records into one record shows more dispositions than records.
Each input that the action consumed has a disposition, although only one output contains
the inputs. Each input that the action consumed and that has no row of its own shows
`reason=consumed_into_output`. A FILE action that makes many records from one record also shows more dispositions.
The reason is that the action gives a new identity to each new row. The dispositions count these rows next to the inputs that made
them. Neither case is data loss.

For the same reason, [`retry`](./retry)
operates on inputs. To retry a record is to run the failed input again.

`Records` counts each record that the store keeps under the action. This count is not the same as
the number of records that the action produced successfully. The output of the action keeps a placeholder for each record that failed, or that a guard skip or a cascade skip
skipped. The placeholder lets downstream
actions still see the record. `Records` counts these placeholders. The `rewrite`
row above shows this: 4 successes and 21 guard skips, `Records 25`. The run line gives the
same data: `✓ rewrite  25 records in 1.2s — 21 skipped by guard`. Thus a high
`Records` count alone does not prove that the action worked. Compare it with
the `Failed checks`, `Failed`, `Guard skipped`, `Unprocessed` and `Passthrough` columns. For
the details, use `--quarantined`.

`Records` also reads what is in the store *now*, not only the output of this run.
A second run of a workflow can use input files with different names. The records of the earlier
run then stay in the store. `Records` counts them too. `agac run --fresh` clears them. A
`?` means that the command could not read the count at all. A `?` is not the same as zero.

An action with an action-level row shows in a second table, with the title `Action-level state`. An example is an action that halted after it used all its retries.
After the table, a hint tells you that `agac run` does not run a halted action again.
To resume a halted action, use `agac retry`. To start it again from the beginning, use `agac run --fresh`.

## Examples

### Full Workflow Overview

```bash
agac dispositions -a my_workflow
```

### One Action Only

```bash
agac dispositions -a my_workflow --action extract_facts
```

### Inspect Stuck Records

`--quarantined` lists each failed, exhausted or unprocessed record. For each record, it gives the action, the record ID, the disposition and the reason. Use this list to decide what to [`retry`](./retry):

```bash
agac dispositions -a my_workflow --quarantined
```

`retry` operates on the failed and exhausted records. The list gives each unprocessed record with the
reason that no answer reached it. The reason tells you where to look. The reasons are:

- An upstream failure (`upstream_unprocessed`)
- A guard skip (`guard_skip`)
- A `granularity: File` tool did not include the record (`tool_missing_record`)
- A `granularity: File` tool merged the record into the row of a different record (`consumed_into_another_record`)

When no record is stuck, the command reports `No quarantined records found.`

:::note[Run from Anywhere]
You can run this command from any subdirectory in your project.
:::
