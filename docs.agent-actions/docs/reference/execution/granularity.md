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
  granularity: file
  kind: tool
  impl: deduplicate_by_similarity
```

**When to use:**
- Deduplication across records
- Aggregation and summarization
- File exports (Excel, CSV)
- Cross-record validation

:::warning Constraints
**File granularity only works with tool actions** (`kind: tool`). LLM actions must use Record granularity.

**Guards are not supported** with File granularity.
:::

## Tool Implementation

### Record-Level Tool

```python
from agent_actions import udf_tool

@udf_tool
def validate_email(data, **kwargs):
    """Process single record."""
    email = data.get('email', '')
    return {"valid": is_valid_email(email)}
```

### File-Level Tool

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def deduplicate_facts(records, **kwargs):
    """Process entire array of records."""
    seen = set()
    unique = []
    for record in records:
        key = record.get('fact_text')
        if key not in seen:
            seen.add(key)
            unique.append(record)
    return unique
```

## Mixing Granularities

```yaml
actions:
  - name: extract_facts
    granularity: record

  - name: deduplicate
    dependencies: extract_facts
    granularity: file
    kind: tool
    impl: deduplicate

  - name: enrich_facts
    dependencies: deduplicate
    granularity: record
```

### Transitions

- **Record → File**: Records collected into array for file-level action
- **File → Record**: Array elements distributed to record-level processing

## Output Wrapping

File mode tools have output automatically wrapped with metadata:

```json
{
  "source_guid": "abc-123",
  "content": {"question": "What is MCP?"},
  "target_id": "new-uuid-1",
  "node_id": "flatten_questions_xyz_0",
  "lineage": ["extract_qa_previous", "flatten_questions_xyz_0"]
}
```

To maintain lineage, copy `source_guid` from input records to output.

## See Also

- [Tool Actions](../tools#granularity) - Tool granularity configuration
- [Run Modes](./run-modes) - Batch vs online execution
- [Guards](./guards) - Conditional execution (record only)
