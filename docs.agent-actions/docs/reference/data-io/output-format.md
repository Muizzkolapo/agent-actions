---
title: Output Format
sidebar_position: 3
---

# Output Format

> **Storage backend:** SQLite as of v0.2.6. File paths under `agent_io/target/.../data.json` in older snippets are stale; this page describes the current SQLite layout.

Where does your data end up after an agentic workflow runs? Action outputs are written to a single SQLite database per workflow at `agent_io/store/<workflow>.db`. Every action's output rows live in the `target_data` table, keyed by `action_name`. This layout makes outputs easy to query, durable across reruns, and trivially deduplicable.

## Storage Layout

```
<project_dir>/
└── agent_io/
    ├── staging/             # Raw input files (unchanged)
    └── store/
        └── <workflow>.db    # SQLite database — all source, target, disposition, and trace data
```

There is exactly one `.db` file per workflow. The framework creates and migrates it automatically on `agac run`.

## Tables

The SQLite database carries five framework-owned tables:

| Table                 | Purpose                                                                                  |
|-----------------------|------------------------------------------------------------------------------------------|
| `source_data`         | Staged input records, deduplicated by `(relative_path, source_guid)`                     |
| `target_data`         | Per-action output records — one row per `(action_name, relative_path)`                   |
| `record_disposition`  | Per-record dispositions (success/failed/exhausted/skipped) emitted by each action        |
| `prompt_trace`        | Compiled prompt + LLM response per record per attempt (online and batch)                 |
| `checkpoint_output`   | Mid-action checkpoint records (used for resumable batch retrieval and reprompt recovery) |

Plus one bookkeeping table `workflow_metadata` for run-level key/value state.

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

Each row stores **all records produced by `action_name` for a given input file** (`relative_path`) as a single JSON array in the `data` column. Use `json_each(data)` to fan rows out into individual records, and `json_extract` to pull fields.

## Record Structure

Each element of the JSON array in `data` is a record with this shape:

```json
{
  "source_guid": "cbbd09ca-2503-591c-b712-4c378c101b9d",
  "node_id": "extract_facts_354c6e1e-4925-403b-9748-52f9386bc154",
  "target_id": "6059b048-9adc-4497-be79-fe6dd04544eb",
  "parent_target_id": "64058522-1cc5-4fea-9372-ade1ecc64fc1",
  "root_target_id": "e1bec28c-c709-4646-845a-2be2bbc8eab1",
  "content": {
    "facts": [...],
    "count": 5
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
| `source_guid`        | Links back to the original source row in `source_data`            |
| `node_id`            | Action that produced this output (includes run UUID)              |
| `target_id`          | Unique identifier for this output record                          |
| `parent_target_id`   | ID of the upstream record that produced this output               |
| `root_target_id`     | ID of the original source record                                  |
| `content`            | LLM/tool output (schema-validated)                                |
| `lineage`            | Array tracking the processing chain                               |
| `metadata`           | Execution metadata (model, provider)                              |

### Metadata Fields

The following fields are metadata and are automatically excluded when extracting content for downstream processing:

- `source_guid`
- `node_id`
- `target_id`
- `parent_target_id`
- `root_target_id`
- `lineage`
- `metadata`
- `chunk_info`
- `_recovery`
- `_unprocessed`

This means when an action references upstream data, it sees the `content` fields organized by upstream action namespace, without these wrappers or system fields.

### Record Types

Records fall into two categories based on whether the action's LLM/tool actually ran:

| How to identify | Meaning | Content |
|----------------|---------|---------|
| `_unprocessed` absent | **Processed** — action ran normally | LLM/tool output |
| `_unprocessed: true` | **Unprocessed** — upstream action failed (API error, missing batch result) | Original upstream content, preserved for lineage |
| `metadata.reason` present | **Skipped** — guard evaluated to false (`on_false: skip`) | Original content, forwarded unchanged |

### System Fields

Records may carry underscore-prefixed system fields that control internal processing:

| Field | Type | Meaning |
|-------|------|---------|
| `_recovery` | `object` | Recovery metadata — present when a record went through [batch recovery](../execution/batch-recovery.md) (retry for missing records and/or reprompt for validation failures). Contains `retry` and/or `reprompt` sub-objects with attempt counts, success status, and timestamps. |
| `_unprocessed` | `true` | Upstream action failed (API error, missing batch result) — automatically skipped by downstream actions |

These fields are excluded from content extraction and should not be set by users. See [Batch Recovery](../execution/batch-recovery.md) for the full `_recovery` structure.

### Content Field

The `content` field contains the action's output, validated against the schema:

```json
"content": {
  "facts": [
    {"fact": "MCP uses JSON-RPC 2.0", "confidence": 0.95},
    {"fact": "Servers expose tools and resources", "confidence": 0.92}
  ],
  "count": 2
}
```

For tool actions, `content` contains the tool return value.

## Passthrough Fields

Fields from `context_scope.passthrough` are preserved at the root level of each record:

```yaml
# Workflow config
context_scope:
  passthrough:
    - source.url
    - source.metadata
```

```json
{
  "source_guid": "doc_1",
  "content": {...},
  "url": "https://example.com",
  "metadata": {"author": "John"}
}
```

## Reading Outputs

### What actions ran, and how many records did each produce

```bash
sqlite3 agent_io/store/<workflow>.db "
  SELECT action_name, relative_path, record_count
  FROM target_data
  ORDER BY action_name, relative_path
"
```

### Dump every record for one action

```bash
sqlite3 agent_io/store/<workflow>.db "
  SELECT json_extract(r.value, '\$')
  FROM target_data t, json_each(t.data) r
  WHERE t.action_name = 'extract_facts'
"
```

### Extract one field across all records for an action

```bash
sqlite3 agent_io/store/<workflow>.db "
  SELECT json_extract(r.value, '\$.content.headline')
  FROM target_data t, json_each(t.data) r
  WHERE t.action_name = 'extract_facts'
"
```

### Locate the row for one source record

```bash
sqlite3 agent_io/store/<workflow>.db "
  SELECT t.action_name, json_extract(r.value, '\$.target_id')
  FROM target_data t, json_each(t.data) r
  WHERE json_extract(r.value, '\$.source_guid') = '<source_guid>'
"
```

## Clean Outputs

Remove previous outputs before a fresh run:

```bash
agac run -a my_workflow --fresh
```

`--fresh` truncates the relevant tables (`source_data`, `target_data`, `record_disposition`, `prompt_trace`, `checkpoint_output`) without deleting the database file. Use `agac clean --all` to drop the database file entirely.

## See Also

- [Input Formats](./input-formats.md) — How to structure input data
- [Data Lineage](./data-lineage.md) — Ancestry tracking for parallel branches and merges
- [Artifacts](../execution/artifacts.md) — Run tracking and detailed output structure
- [Context Scope](../context/context-scope.md) — Passthrough configuration
- [Prompt Traces](./prompt-traces.md) — Compiled prompts and LLM responses per record
