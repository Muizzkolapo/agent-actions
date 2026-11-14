---
title: Output Format
sidebar_position: 3
---

# Output Format

:::note[Storage backend]
SQLite. This page describes the SQLite layout (`agent_io/store/<workflow>.db`, table `target_data`).
:::

After a workflow runs, the action outputs are in a single SQLite database for each workflow, at `agent_io/store/<workflow>.db`. The output rows of every action are in the `target_data` table, with the key `action_name`. With this layout, outputs are easy to query, durable across reruns and easy to deduplicate.

## Storage Layout

```
<project_dir>/
└── agent_io/
    ├── staging/             # Raw input files (unchanged)
    └── store/
        └── <workflow>.db    # SQLite database — all source, target, disposition, and trace data
```

There is exactly one `.db` file for each workflow. The framework creates and migrates it automatically on `agac run`.

## Tables

The SQLite database has six tables that the framework owns:

| Table                 | Purpose                                                                                  |
|-----------------------|------------------------------------------------------------------------------------------|
| `source_data`         | Staged input records, deduplicated by `(relative_path, source_guid)`                     |
| `target_data`         | Output records of each action, one row for each `(action_name, relative_path)` |
| `record_disposition`  | Dispositions of each record (`success`, `failed`, `exhausted`, `skipped`, `filtered`, `passthrough`, `deferred`, `unprocessed`) that each action emits |
| `prompt_trace`        | The compiled prompt and the LLM response for each record and each attempt (online and batch) |
| `prompt_trace_dictionary` | Compression dictionaries for the text columns of `prompt_trace`                    |
| `checkpoint_output`   | Mid-action checkpoint records (used for resumable batch retrieval and repair recovery) |

The database also has one bookkeeping table, `workflow_metadata`, for key/value state at the run level.

## `target_data` Schema

```sql
CREATE TABLE target_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name   TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    data          TEXT NOT NULL,          -- JSON array of records
    record_count  INTEGER,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(action_name, relative_path)
)
```

Each row stores **all records that `action_name` produced for a given input file** (`relative_path`). The row stores these records as a single JSON array in the `data` column, in compressed form. Read the records with [`agac records`](../cli/records) (recipes below). `sqlite3` shows the column as a blob.

## Record Structure

Each element of the JSON array in `data` is a record. This example record comes from an action downstream of the first action:

```json
{
  "source_guid": "cbbd09ca-2503-591c-b712-4c378c101b9d",
  "node_id": "extract_facts_354c6e1e-4925-403b-9748-52f9386bc154",
  "target_id": "6059b048-9adc-4497-be79-fe6dd04544eb",
  "parent_target_id": "64058522-1cc5-4fea-9372-ade1ecc64fc1",
  "root_target_id": "e1bec28c-c709-4646-845a-2be2bbc8eab1",
  "content": {
    "source": {"url": "https://example.com"},
    "extract_facts": {
      "facts": [...],
      "count": 5
    }
  },
  "lineage": [
    "extract_facts_354c6e1e-4925-403b-9748-52f9386bc154"
  ],
  "metadata": {
    "model": "gpt-4o-mini",
    "provider": "openai"
  }
}
```

### Fields

| Field                | Description                                                       |
|----------------------|-------------------------------------------------------------------|
| `source_guid`        | Links to the original source row in `source_data` |
| `node_id`            | The action that produced this output (includes the run UUID) |
| `target_id`          | The unique identifier of this output record |
| `parent_target_id`   | The ID of the upstream record that produced this output (absent on the records of the first action) |
| `root_target_id`     | The `target_id` of the record of the first action for this source record (absent on the records of the first action) |
| `content`            | Fields by namespace. The staged input is under `source`. The output of each upstream action is under the name of that action. The output of this action (schema-validated) is under its own name. |
| `lineage`            | An array that tracks the processing chain |
| `metadata`           | Execution metadata, for example `model` and `provider` |

### Metadata Fields

These fields are metadata. They are automatically excluded when content is extracted for downstream processing:

- `source_guid`
- `parent_source_guid`
- `producer_source_guids`
- `repeat_of_source_guid`
- `aggregated_by`
- `folded_sources`
- `node_id`
- `target_id`
- `parent_target_id`
- `root_target_id`
- `lineage`
- `metadata`
- `chunk_info`
- `_recovery`
- `_unprocessed`
- `_state`
- `_state_history`
- `_state_schema_version`

Thus, when an action refers to upstream data, it sees the `content` fields, organized by the namespace of each upstream action. It does not see these wrappers or system fields.

### Record Types

The `_state` field tells whether the LLM/tool of the action ran for the record:

| `_state` | Meaning | Content |
|----------|---------|---------|
| `processed` | **Processed** — the action ran normally | LLM/tool output under the namespace of the action |
| `guard_skipped` | **Skipped** — the guard evaluated to false (`on_false: skip`). `metadata.reason` is `guard_skip`. | Original content, forwarded with the namespace of the action set to `null` |
| `cascade_skipped` | **Unprocessed** — an upstream action failed or blocked the record. `metadata.reason` names the cause, for example `upstream_unprocessed`. | Original upstream content, preserved for lineage |
| `failed`, `exhausted` | The action failed on the record, or its retries were exhausted | Original content, preserved for lineage |

A skipped or unprocessed record is a tombstone. It carries `_tombstone: true` and `_tombstone_reason`.

### System Fields

Records may carry system fields with an underscore prefix. These fields control internal processing:

| Field | Type | Meaning |
|-------|------|---------|
| `_recovery` | `object` | Recovery metadata. It is present when a record went through [batch recovery](../execution/batch-recovery.md) (retry for missing records, repair for expectation failures, or both). It contains a `retry` sub-object, an `expectations` sub-object, or both, with attempt counts and status. |
| `_state` | `string` | The lifecycle state of the record: `active`, `processed`, `guard_skipped`, `cascade_skipped`, `failed` or `exhausted` |
| `_tombstone` | `true` | The record is a placeholder for a skipped, unprocessed or failed record |

These fields are excluded from content extraction. Users should not set them. See [Batch Recovery](../execution/batch-recovery.md) for the full `_recovery` structure.

### Content Field

The `content` field holds one namespace for each source of data. The output of the action, validated against the schema, is under the name of the action:

```json
"content": {
  "source": {"url": "https://example.com"},
  "extract_facts": {
    "facts": [
      {"fact": "MCP uses JSON-RPC 2.0", "confidence": 0.95},
      {"fact": "Servers expose tools and resources", "confidence": 0.92}
    ],
    "count": 2
  }
}
```

For tool actions, the namespace contains the tool return value.

## Passthrough Fields

Fields from `context_scope.passthrough` are kept on the output record of the action, under
the namespace that they came from. They are not under the namespace of the action, and not at the root:

```yaml
# Workflow config, on an action named summarize
context_scope:
  passthrough:
    - source.url
    - source.metadata
```

```json
{
  "source_guid": "doc_1",
  "content": {
    "source": {"url": "https://example.com", "metadata": {"author": "John"}},
    "summarize": {...}
  }
}
```

A downstream action reads them as `source.url` and `source.metadata`, never as `summarize.url`.
See [Context Scope](../context/context-scope.md#passthrough-directive).

## Reading Outputs

### List the actions that ran and the record count of each action {/* #what-actions-ran-and-how-many-records-did-each-produce */}

```bash
sqlite3 agent_io/store/<workflow>.db "
  SELECT action_name, relative_path, record_count
  FROM target_data
  ORDER BY action_name, relative_path
"
```

The `data` column is compressed in the store. Thus you read the records themselves with [`agac records`](../cli/records), not with sqlite3. Each record that `agac records` prints carries `_action` and `_file`.

### Dump every record for one action

```bash
agac records -w <workflow> -a extract_facts
```

### Extract one field across all records for an action

```bash
agac records -w <workflow> -a extract_facts --field content.headline
```

### Locate the records for one source record {/* #locate-the-rows-for-one-source-record */}

```bash
# Every action's record for that source, each with its _action and target_id
agac records -w <workflow> --source-guid <source_guid>
```

## Clean Outputs

Remove the previous outputs before a fresh run:

```bash
agac run -a my_workflow --fresh
```

`--fresh` truncates the relevant tables (`source_data`, `target_data`, `record_disposition`, `prompt_trace`, `checkpoint_output`). It does not delete the database file. `agac clean --all` removes all the `agent_io` directories, including `staging/`, `target/` and the database in the store. It asks for confirmation unless `--force` is set. The store folder stays. It holds only the empty run lock file `<workflow>.db.lock`.

## See Also

- [Input Formats](./input-formats.md) — How to structure input data
- [Data Lineage](./data-lineage.md) — Ancestry tracking for parallel branches and merges
- [Artifacts](../execution/artifacts.md) — Run tracking and detailed output structure
- [Context Scope](../context/context-scope.md) — Passthrough configuration
- [Prompt Traces](./prompt-traces.md) — Compiled prompts and LLM responses for each record
