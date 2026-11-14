---
title: Granularity
sidebar_position: 5
---

# Granularity

Granularity sets the scope of an action. The action processes one record at a time, or all of the records together.

## Overview

| Granularity | Processing Scope | Use Case |
|-------------|------------------|----------|
| **record** | One record at a time | Transformations, validations, LLM calls |
| **file** | All records together | Deduplication, exports, aggregation |

## Configuration

```yaml
defaults:
  granularity: record

actions:
  - name: extract_items        # record, from defaults

  - name: aggregate_results
    kind: tool
    impl: aggregate_results
    granularity: file
    dependencies: [extract_items]
```

## Record Granularity (Default)

The action processes each record independently. Thus the records can run in parallel.

```yaml
- name: validate_email
  granularity: record
  kind: tool
  impl: validate_email
```

**When to use:**
- A transformation of each record
- A validation of each record
- An LLM call for each record
- Field extraction and enrichment

## File Granularity

All of the records are available together, for operations across records.

```yaml
- name: deduplicate_facts
  dependencies: [extract_facts]
  granularity: file
  kind: tool
  impl: deduplicate_by_similarity
```

A File action needs an upstream action. The File action reads the file of records that the upstream action wrote. The first action of a workflow reads the staged input one record at a time. Thus pre-flight refuses a File action that has no `dependencies`.

**When to use:**
- Deduplication across records
- Aggregation and summarization
- File exports (Excel, CSV)
- Cross-record validation

:::warning[CAUTION]
**File granularity works only with tool actions and HITL actions** (`kind: tool` or `kind: hitl`). LLM actions must use Record granularity. `agac inspect` and `agac run` refuse `granularity: file` on an LLM action. A `granularity: file` under `defaults:` applies only to the tools of the workflow. An LLM action that inherits it runs at Record.

**HITL actions require File granularity.** If you set `granularity: record` on a HITL action, the framework raises a `ConfigurationError`. The default granularity of a HITL action is `file`.

**A guard on a File granularity action** is a pre-filter for each record. The guard examines each record before the framework gives the array to the action. For more data, see [Guards](./guards).
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

A FILE tool receives a list with one item for each record. Each item holds the fields that the action observes, as flat keys. A field that `observe` names keeps its bare name. A key is `action_name.field` only where two observed names really collide. A collision occurs in these cases:

- Two named fields have the same name.
- A wildcard field has the same name as a named field. The named field keeps the bare key.
- The action observes several actions by wildcard.

No action name wraps the fields, and the item has no `content`. To keep the lineage, return the items that you received.

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

:::note[Record Identity]
The framework tracks the identity of each item that a FILE tool receives. When you return an item that you received, the framework automatically matches it to the correct input. The framework then extends the lineage chain. For an aggregation (new data), the framework makes a new record from a `FileUDFResult` output that declares `source_index: None`. The framework refuses a plain new dict in a list.
:::

For an aggregation, return a `FileUDFResult` whose output declares `source_index: None`.

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

- **Record → File**: The framework collects the records into an array for the file-level action.
- **File → Record**: The framework gives each element of the array to record-level processing.

## Output Processing

After a FILE tool returns, the framework does these steps:

1. **It matches outputs to inputs by `source_index`.** These outputs extend the lineage of their input: a `TrackedItem` that the tool returned unchanged, or a `FileUDFResult` output that names its input.
2. **It makes a new record from each output that declares `source_index: None`.** Each new record gets new lineage (for example, aggregation results). It carries `aggregated_by`, which is the name of the action. Each record that downstream actions make from it also carries `aggregated_by`. From each upstream namespace, such a row carries only the fields that are equal on all inputs of the file. Thus a downstream action can still read a value that all inputs shared. The row carries the state history of no input.
3. **It stores a tombstone for each input that no output names.** The tool dropped that input, independent of the number of rows that it wrote for the other inputs. Thus the record is `unprocessed` with reason `tool_missing_record`, and the downstream actions skip it. An output that consumes several inputs names each of them in its `source_index` list. When an output declares `source_index: None`, that output may have consumed any input. Thus an input that no output names gets no row and no disposition.
4. **It wraps and enriches the output.** It assigns a new `target_id` and a new `node_id`, and it extends the `lineage` chain.

```json
{
  "source_guid": "abc-123",
  "content": {"question": "What is MCP?"},
  "target_id": "new-uuid-1",
  "node_id": "deduplicate_facts_xyz_0",
  "lineage": ["extract_qa_abc", "flatten_questions_def_0", "deduplicate_facts_xyz_0"]
}
```

Lineage follows `source_index`. The framework assigns `source_guid` itself. If a tool sets a value on a record that it returns, the framework drops that value.

An output that names several inputs takes the identity of the first input. The exception is an output that joins a split again. The output takes the `source_guid` of the source when all of these conditions are true:

1. The output names all of the records of its file that an upstream action split from one source.
2. The output names only those records.
3. No other output names one of those records.

That `source_guid` is the value that the record would hold if it was never split. A [fan-in](../context/context-scope.md) then pairs the output with the records of that source from other branches.

Each other output that names several inputs folds the other inputs into the first input. With `source_index: [a, b]`, `b` has no row of its own downstream of the tool. The disposition of `b` at the tool is `success` with reason `consumed_into_output`. When an output declares `source_index: None`, `b` has no disposition. The row lists `b`, with the action, under `folded_sources`. The records that downstream actions make from the row keep `folded_sources`. The downstream actions that read only this branch run on the row.

A fan-in next to another branch holds `b` only from the other branch. Thus the fan-in leaves `b` `unprocessed`, with reason `consumed_into_another_record`. The fan-in does not run `b` with the fields of this branch empty. These results occur:

- The tombstone of `b` at the fan-in names the row that `b` went into, as `metadata.consumed_into`.
- The run logs a warning that names `b` and the row.
- `agac dispositions` counts `b` under Unprocessed.

The version merge (`version_consumption`) does the same thing for a versioned tool that folds `b` in one version and keeps it in another. The merge leaves `b` `unprocessed` with that reason. It does not run `b` without the output of the version that folds it.

### When a FILE Tool Fails

A FILE tool processes its whole file at one time. Thus the framework records a failure against the records that the tool received:

- **The tool raises an error, or it returns output that the framework cannot match to its inputs.** This output can be a plain dict in a list, or output that is not a list and not a `FileUDFResult`. It can also be a row whose parent `source_index` names no input. The framework marks each record of that file `failed` with the error. The framework stores the other files of the action.
- **A record does not have a field that the action observes, or the framework cannot resolve its source.** The framework marks that record `failed` before the tool runs. The reason names each missing field (`context_scope.observe fields 'prep.region', 'prep.zone' not found in this record`). The tool receives the remaining records of the file. The guard does not examine such a record. The context of the guard needs each observed field. Thus a guard that would skip the record cannot read it. The framework does not refuse a record that an upstream action left failed. That record stays `unprocessed`. RECORD mode fails the same record in the same way. The framework prints no guard message, because no guard acted.
- **An output fails the schema of the action.** After the tool returns, the framework examines each output independently. When the refused output names one input by `source_index`, the framework marks that record `failed` with the validation message. The framework drops each other output of that record, and it stores the remaining records of the file. In these cases, the framework marks each record of the file `failed`:
  - The refused output names several inputs, or no input (`source_index: None`).
  - A dropped output also answers another record.

The action ends `completed_with_failures`. When no record succeeds, the action ends `failed`. `agac retry` runs the tool again over each file that holds a failed record, on the whole file. After `agac run --rerun` resets the action, the framework stores a file whose records all fail, with those failures. Thus the framework keeps no row from before the reset.

### When a Retry Reaches a FILE Tool

Each row of a FILE tool may depend on all of the records of the file. Thus a retry runs the tool over the whole file. When `agac retry` gets to any record of a file at a FILE tool, these results occur:

1. The tool receives each record of the file that the guard passes and that no upstream action left failed.
2. The framework replaces all of the rows that the action held for that file.

These results occur when the record failed at the tool, and also when an upstream action repaired the record.

If the tool writes a row again exactly as it was, the row is the same row. It keeps the identifiers that the framework stored it under. A roll-up row (`source_index: None`) follows the same rule. It carries only the data that all inputs share. Thus a retry that changes nothing writes the roll-up row again as it was, and the row keeps its identity. A retry that changes an input that the roll-up row depends on writes a different row. That row gets a new identity, and the downstream actions process it again.

Each downstream action also processes that file again, for each record whose row changed. The reason is that the downstream action computed its data for that record from the previous output of the tool. The data of a downstream action for a record whose row did not change stays. A file that holds no record that the retry names keeps its rows. See [A FILE tool runs over the whole file](../cli/retry#a-file-tool-runs-over-the-whole-file).

A HITL action is the exception. A retry shows the reviewer only the records that the retry names. The other records keep their current decision.

## See Also

- [Tool Actions](../tools#granularity) - Configure the granularity of a tool
- [Run Modes](./run-modes) - Batch execution and online execution
- [Guards](./guards) - Conditional execution (the two granularities)
