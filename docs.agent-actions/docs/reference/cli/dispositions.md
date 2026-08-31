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
┃ Action  ┃ Success ┃ Failed ┃ Exhaust… ┃ Unproc… ┃ Passthr… ┃ Filter… ┃ Total ┃
│ extract │      25 │      0 │        0 │       0 │        0 │       0 │    25 │
│ rewrite │       4 │      0 │        0 │       0 │       21 │       0 │    25 │
│ write_… │       1 │      0 │        0 │      21 │        0 │       0 │    22 │
```

| Disposition | Meaning |
|-------------|---------|
| **Success** | The record was processed by the action |
| **Failed** | Processing failed for the record |
| **Exhausted** | The record failed and its retries are used up |
| **Unprocessed** | An upstream failure cascaded — the action never saw the record |
| **Passthrough** | A guard condition skipped the record; it flows on unchanged |
| **Filtered** | The action removed the record from the stream |

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
