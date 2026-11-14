---
title: records Command
description: Print, as JSON, the records that an action stored, or the input of each failed record
sidebar_position: 7
---

# records Command

The `records` command prints the records that an action stored, as a JSON list. With `--snapshots`, it prints a different thing: the input with which each failed or exhausted record was processed.

```bash
agac records -w <workflow-name> [options]
```

The store keeps these payloads compressed. Thus `sqlite3` shows `target_data.data` and `record_disposition.input_snapshot` as blobs. Read them with this command. The command opens the store read-only. You can still query the metadata columns (`action_name`, `relative_path`, `record_count`, `disposition`, `reason`) with `sqlite3`.

## Options

| Option | Description |
|--------|-------------|
| `-w, --workflow TEXT` | The name of the workflow configuration file (required) |
| `-a, --action TEXT` | Only the records of this action. If you omit it, the command uses each action that has stored records. |
| `--source-guid TEXT` | Only the records of this source record, in each action that holds one |
| `--file TEXT` | Only the records of this stored file (its `relative_path`). Without `-a`, the command uses each action that stores the file. With `--snapshots`, the command uses only the records that failed in the file. |
| `--field TEXT` | Print one value for each record, not the full record. The value is a dotted path into the record, for example `content.extract_facts.headline`. The keys of the stored `content` are the action names. If the record does not have the path, the command prints `null`. |
| `--snapshots` | Print the input with which each failed or exhausted record was processed, not the stored records. `-a`, `--source-guid` and `--file` make the output smaller. |

The command prints each record as the store keeps it. It adds `_action` (the action that stored the record) and `_file` (the file that the record is stored under). `--field` can name each of these two fields.

## Examples

```bash
# Every record an action stored
agac records -w my_workflow -a extract_facts

# One field of each
agac records -w my_workflow -a extract_facts --field content.extract_facts.headline

# One source record, in every action that holds it
agac records -w my_workflow --source-guid <source_guid>

# Which actions hold it
agac records -w my_workflow --source-guid <source_guid> --field _action

# The input each failed or exhausted record was processed with
agac records -w my_workflow --snapshots
agac records -w my_workflow -a extract_facts --snapshots
```

The command prints a snapshot in this format:

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

`input_snapshot` is the record as JSON. If the store truncated the snapshot at 10KB, the command prints it as `{"__truncated__": true, "partial": "..."}`.

## Errors

| Message | Cause |
|---------|-------|
| `No store for workflow '<name>' at <path>` | The workflow did not run. Thus it has no store. |
| `No stored records for action '<action>' in <path>` | The action stored nothing. The action did not run, or each record was filtered, or `--fresh` cleared the records of the action. |
| `File '<file>' not found for node '<action>'` | The action stores no file under that `relative_path`. |
| `target_data for action '<action>' file '<file>' cannot be read: ...` | The command cannot decode a stored row. The cause is a corrupt value, or a dictionary that the store no longer holds. The same row stops a resume or a retry. Run the action again with `--fresh`. |

For the contents of a stored record, see [Output Format](../data-io/output-format.md). For when the store writes a snapshot, see [Record Lifecycle](../../guides/record-lifecycle.md). For a table view in pages, see [`preview`](./preview).
