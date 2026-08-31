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
┃ Action  ┃ Success ┃ Failed ┃ Exhaust… ┃ Unproc… ┃ Passthr… ┃ Filter… ┃ Total ┃ Records ┃
│ extract │      25 │      0 │        0 │       0 │        0 │       0 │    25 │      25 │
│ rewrite │       4 │      0 │        0 │       0 │       21 │       0 │    25 │      25 │
│ split   │       1 │      0 │        0 │       0 │        0 │       0 │     1 │       5 │
```

| Disposition | Meaning |
|-------------|---------|
| **Success** | The record was processed by the action |
| **Failed** | Processing failed for the record |
| **Exhausted** | The record failed and its retries are used up |
| **Unprocessed** | An upstream failure cascaded — the action never saw the record |
| **Passthrough** | A guard condition skipped the record; it flows on unchanged |
| **Filtered** | The action removed the record from the stream |

### Why Total and Records can differ

**A disposition is one row per input record per action.** `Total` counts the
records an action *consumed*; `Records` counts the records now stored under it,
which for an action that has run is what it produced. They match for an action
that turns one record into one record, and they legitimately differ otherwise —
`split` above turned one input into five outputs, so its single disposition
sits beside five records.

An action that folds records together shows the reverse: more dispositions than
records, because every input it consumed is accounted for even though only one
output carries them. Neither case is data loss.

The children an action creates are accounted at the actions that *consume*
them, not at the one that produced them. This is also why [`retry`](./retry)
targets inputs: retrying a record means re-running the input that failed.

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

When nothing is stuck it reports `No quarantined records found.`

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::
