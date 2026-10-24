---
title: records Command
description: Print the records an action stored, or the input each failed record was processed with, as JSON
sidebar_position: 7
---

# records Command

The `records` command prints the records an action stored, as a JSON list. With `--snapshots` it prints instead the input each failed or exhausted record was processed with.

```bash
agac records -w <workflow-name> [options]
```

The store keeps these payloads compressed, so `sqlite3` shows `target_data.data` and `record_disposition.input_snapshot` as blobs. Read them with this command. It opens the store read-only; the metadata columns (`action_name`, `relative_path`, `record_count`, `disposition`, `reason`) stay queryable with `sqlite3`.

## Options

| Option | Description |
|--------|-------------|
| `-w, --workflow TEXT` | Workflow configuration file name (required) |
| `-a, --action TEXT` | Only this action's records. Every action with stored records when omitted. |
| `--source-guid TEXT` | Only the records of this source record, in whichever actions hold one |
| `--file TEXT` | Only the records of this stored file (its `relative_path`) |
| `--field TEXT` | Print one value per record instead of the record: a dotted path into it, such as `content.headline`. A path the record does not have prints `null`. |
| `--snapshots` | Print the input each failed or exhausted record was processed with, instead of stored records |

Each record prints as stored, plus `_action` (the action that stored it) and `_file` (the file it is stored under). Both can be named by `--field`.

## Examples

```bash
# Every record an action stored
agac records -w my_workflow -a extract_facts

# One field of each
agac records -w my_workflow -a extract_facts --field content.headline

# One source record, in every action that holds it
agac records -w my_workflow --source-guid <source_guid>

# Which actions hold it
agac records -w my_workflow --source-guid <source_guid> --field _action

# The input each failed or exhausted record was processed with
agac records -w my_workflow --snapshots
agac records -w my_workflow -a extract_facts --snapshots
```

A snapshot prints as:

```json
[
  {
    "_action": "extract_facts",
    "record_id": "<source_guid>",
    "disposition": "failed",
    "reason": "llm_error",
    "relative_path": "pages.json",
    "input_snapshot": { "source_guid": "<source_guid>", "content": { "...": "..." } }
  }
]
```

`input_snapshot` is the record as JSON; one the store truncated at 10KB prints as `{"__truncated__": true, "partial": "..."}`.

## Errors

| Message | Cause |
|---------|-------|
| `No store for workflow '<name>' at <path>` | The workflow has not run, so it has no store. |
| `No stored records for action '<action>' in <path>` | The action stored nothing: it has not run, every record was filtered, or `--fresh` cleared it. |
| `File '<file>' not found for node '<action>'` | The action stores no file under that `relative_path`. |
| `target_data for action '<action>' file '<file>' cannot be read: ...` | A stored row cannot be decoded (a corrupt value, or a dictionary the store no longer holds). The same row stops a resume or retry; re-run the action with `--fresh`. |

See [Output Format](../data-io/output-format.md) for what a stored record holds, [Record Lifecycle](../../guides/record-lifecycle.md) for when a snapshot is written, and [`preview`](./preview) for a paged table view.
