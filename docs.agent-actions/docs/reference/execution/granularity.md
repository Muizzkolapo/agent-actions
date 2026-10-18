---
title: Granularity
sidebar_position: 5
---

# Granularity

Granularity controls whether an action processes one record at a time or the entire dataset.

## Overview

| Granularity | Processing Scope | Use Case |
|-------------|------------------|----------|
| **record** | Per-item | Transformations, validations, LLM calls |
| **file** | All items | Deduplication, exports, aggregation |

## Configuration

```yaml
defaults:
  granularity: record

actions:
  - name: aggregate_results
    granularity: file
```

## Record Granularity (Default)

Each record processed independently, enabling parallel execution.

```yaml
- name: validate_email
  granularity: record
  kind: tool
  impl: validate_email
```

**When to use:**
- Individual item transformations
- Per-record validations
- LLM calls per item
- Field extraction and enrichment

## File Granularity

All records available at once for cross-record operations.

```yaml
- name: deduplicate_facts
  dependencies: [extract_facts]
  granularity: file
  kind: tool
  impl: deduplicate_by_similarity
```

A File action needs an action before it: it reads the file of records that action wrote. The first action of a workflow reads the staged input one record at a time, so pre-flight refuses a File action with no `dependencies`.

**When to use:**
- Deduplication across records
- Aggregation and summarization
- File exports (Excel, CSV)
- Cross-record validation

:::warning Constraints
**File granularity only works with tool and HITL actions** (`kind: tool` or `kind: hitl`). LLM actions must use Record granularity.

**HITL actions require File granularity** — setting `granularity: record` on a HITL action raises a `ConfigurationError`. HITL defaults to `file` automatically.

**Guards with File granularity** act as a per-record pre-filter. The guard evaluates each record before the array is passed to the action. See [Guards](./guards) for details.
:::

## Tool Implementation

### Record-Level Tool

```python
from agent_actions import udf_tool

@udf_tool
def validate_email(data, **kwargs):
    """Process single record."""
    email = data["source"]["email"]
    return {"valid": is_valid_email(email)}
```

### File-Level Tool

FILE tools receive a list with one item per record. Each item holds the fields the action observes as flat keys: the bare field name, or `action_name.field` where two observed names could collide (for example, when the tool observes several actions by wildcard). There is no action name around them and no `content`. Return the items you received to preserve lineage.

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def deduplicate_facts(records, **kwargs):
    """Dedup — return the items received to preserve lineage tracking."""
    seen = set()
    unique = []
    for record in records:
        key = record["fact_text"]
        if key not in seen:
            seen.add(key)
            unique.append(record)  # pass through the item as received
    return unique
```

:::tip Record Identity
The framework tracks the identity of each item a FILE tool receives. When you return the item you were given, the framework automatically matches it to the correct input and extends the lineage chain. For aggregation (creating new data), return a `FileUDFResult` whose output declares `source_index: None` — the framework treats it as a new record. A plain new dict in a list is rejected.
:::

## Mixing Granularities

```yaml
actions:
  - name: extract_facts
    granularity: record

  - name: deduplicate
    dependencies: [extract_facts]
    granularity: file
    kind: tool
    impl: deduplicate

  - name: enrich_facts
    dependencies: [deduplicate]
    granularity: record
```

### Transitions

- **Record → File**: Records collected into array for file-level action
- **File → Record**: Array elements distributed to record-level processing

## Output Processing

After a FILE tool returns, the framework:

1. **Matches outputs to inputs by `source_index`** — a `TrackedItem` returned unchanged, or a `FileUDFResult` output naming the input it came from, extends that input's lineage.
2. **Treats outputs declaring `source_index: None` as new records** — they get fresh lineage (e.g., aggregation results).
3. **Wraps and enriches** — assigns new `target_id`, `node_id`, and extends the `lineage` chain.

```json
{
  "source_guid": "abc-123",
  "content": {"question": "What is MCP?"},
  "target_id": "new-uuid-1",
  "node_id": "deduplicate_facts_xyz_0",
  "lineage": ["extract_qa_abc", "flatten_questions_def_0", "deduplicate_facts_xyz_0"]
}
```

Lineage follows `source_index`; the framework assigns `source_guid` itself, and a value a tool sets on a record it returns is dropped.

An output naming several inputs takes the identity of the first one, with one exception: an output that gathers a split back together. When it names every record of its file that an action above split from one source, and only those, and no other output names any of them, it takes that source's `source_guid`, as the record would hold had it never been split. A [fan-in](../context/context-scope.md) then pairs it with other branches' records of that source.

### When a FILE Tool Fails

A FILE tool answers its whole file at once, so a failure is recorded against the records it was handed:

- **The tool raises**, or returns output that cannot be matched to its inputs (a plain dict in a list, neither a list nor a `FileUDFResult`, or a row whose parent `source_index` names no input): every record of that file is marked `failed` with the error. The action's other files are stored.
- **An output fails the action's schema**: each output is checked on its own after the tool returns. When the refused output names one input by `source_index`, that record is marked `failed` with the validation message, every other output of that record is dropped, and the rest of the file is stored. When it names several inputs or none (`source_index: None`), or a dropped output also answers another record, every record of the file is marked `failed`.

The action ends `completed_with_failures` (`failed` when no record succeeds), and `agac retry` runs the tool again over each file holding a failed record, whole. After an edit resets the action, a file whose every record fails is stored with those failures, so no row from before the edit is kept.

### When a Retry Reaches a FILE Tool

A FILE tool's rows may each depend on every record of the file, so the file is what a retry runs it over. When `agac retry` reaches any record of a file at a FILE tool, whether that record failed at the tool or was repaired above it, the tool is handed every record of the file the guard passes and nothing upstream left failed, and the rows the action held for that file are replaced whole. Every action below it answers that file again too, every record of it, since each row it held there was computed from what the tool wrote before. A file holding no record the retry names keeps its rows. See [A FILE tool runs over the whole file](../cli/retry#a-file-tool-runs-over-the-whole-file).

A HITL action is the exception: a retry shows the reviewer only the records it names, and the other records keep the decision they hold.

## See Also

- [Tool Actions](../tools#granularity) - Tool granularity configuration
- [Run Modes](./run-modes) - Batch vs online execution
- [Guards](./guards) - Conditional execution (both granularities)
