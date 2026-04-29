---
title: Output Format
sidebar_position: 3
---

# Output Format

Where does your data end up after an agentic workflow runs? Action outputs are written to `agent_io/target/` as JSON files, organized by action. This structure makes it easy to inspect what each action produced and trace results back to their sources.

## Directory Structure

```
agent_io/target/
├── extract_facts/
│   └── source_file.json
├── validate_facts/
│   └── source_file.json
└── generate_summary/
    └── source_file.json
```

- Each action creates a subdirectory named after the action
- Source filenames are preserved through the pipeline
- All outputs are JSON arrays

## Output Structure

Each output file contains an array of records:

```json
[
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
]
```

### Fields

| Field | Description |
|-------|-------------|
| `source_guid` | Links back to original source file |
| `node_id` | Action that produced this output (includes run UUID) |
| `target_id` | Unique identifier for this output record |
| `parent_target_id` | ID of the upstream record that produced this output |
| `root_target_id` | ID of the original source record |
| `content` | LLM/tool output (schema-validated) |
| `lineage` | Array tracking the processing chain |
| `metadata` | Execution metadata (model, provider) |

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
- `_state`
- `_transitions`

This means when an action references upstream data, it sees the `content` fields organized by upstream action namespace, without these wrappers or system fields.

### Record Types

Records fall into two categories based on whether the action's LLM/tool actually ran:

| How to identify | Meaning | Content |
|----------------|---------|---------|
| `_state: "committed"` | **Processed** — action ran normally | LLM/tool output |
| `_state: "cascade_skipped"` | **Unprocessed** — upstream action failed (API error, missing batch result) | Original upstream content, preserved for lineage |
| `_state: "guard_skipped"` | **Skipped** — guard evaluated to false (`on_false: skip`) | Original content, forwarded unchanged |

### System Fields

Records may carry underscore-prefixed system fields that control internal processing:

| Field | Type | Meaning |
|-------|------|---------|
| `_recovery` | `object` | Recovery metadata — present when a record went through [batch recovery](../execution/batch-recovery.md) (retry for missing records and/or reprompt for validation failures). Contains `retry` and/or `reprompt` sub-objects with attempt counts, success status, and timestamps. |
| `_state` | `string` | Record state for this action (e.g. `committed`, `guard_skipped`, `failed`, `exhausted`, `cascade_skipped`) |
| `_transitions` | `array` | State transition audit trail (timestamp, action, reason, detail) |

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

Fields from `context_scope.passthrough` are preserved at the root level of the output:

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

### Single File

```bash
cat agent_io/target/extract_facts/document_1.json | jq .
```

### All Outputs from Action

```bash
cat agent_io/target/extract_facts/*.json | jq -s 'add'
```

### Extract Content Only

```bash
jq '.[].content' agent_io/target/extract_facts/document_1.json
```

## Clean Outputs

Remove previous outputs before a fresh run:

```bash
agac clean -a my_workflow
```

This removes `source/` and `target/` directories. Use `--all` to also remove `staging/`.

## See Also

- [Input Formats](./input-formats.md) — How to structure input data
- [Data Lineage](./data-lineage.md) — Ancestry tracking for parallel branches and merges
- [Artifacts](../execution/artifacts.md) — Run tracking and detailed output structure
- [Context Scope](../context/context-scope.md) — Passthrough configuration
