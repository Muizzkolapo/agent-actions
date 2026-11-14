---
title: Data Lineage
sidebar_position: 4
---

# Data Lineage

:::note[Storage backend]
SQLite. This page uses the SQLite layout (`agent_io/store/<workflow>.db`, table `target_data`, where the `data` column of each row is a JSON array of records).
:::

The **Ancestry Chain** tracks data as it flows through parallel branches, merges and splits. It gives complete lineage tracking. This tracking enables complex workflow patterns, for example Diamond, Map-Reduce and Ensemble voting.

## Overview

Each record in Agent Actions carries lineage metadata. This example record comes from an action downstream of the first action:

```json
{
  "source_guid": "cbbd09ca-2503-591c-b712-4c378c101b9d",
  "target_id": "550e8400-e29b-41d4-a716-446655440003",
  "parent_target_id": "550e8400-e29b-41d4-a716-446655440001",
  "root_target_id": "550e8400-e29b-41d4-a716-446655440000",
  "node_id": "merge_abc12345-6789-0abc-def0-123456789abc",
  "lineage": [
    "extract_def45678-1234-5678-9abc-def012345678",
    "validate_ghi78901-2345-6789-abcd-ef0123456789",
    "merge_abc12345-6789-0abc-def0-123456789abc"
  ],
  "content": { ... }
}
```

## Ancestry Fields

| Field | Purpose | Use Case |
|-------|---------|----------|
| `source_guid` | Correlates the records from the same source file | Basic file-level grouping |
| `target_id` | The unique identifier of this record | Tracking of individual records |
| `parent_target_id` | Links to the immediate parent record (absent on the records of the first action) | **Parallel branch merge** (Diamond pattern) |
| `root_target_id` | Links to the record of the first action for the same source record (absent on the records of the first action) | **Map-Reduce** aggregation |
| `lineage` | The array of node IDs that this record passed through | Tracking of a sequential chain |

## How It Works

### Record Lifecycle

When a record flows through an action, the ancestry chain propagates automatically:

**Propagation Rules:**
1. `target_id` = new UUID (unique for each output)
2. `parent_target_id` = the `target_id` of the input (links to the immediate parent)
3. `root_target_id` = the `root_target_id` of the input. If the input has no `root_target_id` (it is a record of the first action), the value is the `target_id` of the input.

### First Record (Root)

The record that the first action writes is the root. It carries `target_id`. It does not have `parent_target_id` or `root_target_id`:

```json
{
  "target_id": "ROOT-UUID"
}
```

Each record downstream of the root takes the `target_id` of the root as its `root_target_id`.
`parent_target_id` is **absent** on root records (not `null`). Use a presence check
(`"parent_target_id" in record`), not `record["parent_target_id"] is None`.

## Parallel Branch Merge (Diamond Pattern)

Multiple actions process the same data in parallel. Then a downstream action needs **all** their outputs.

```yaml
actions:
  - name: validate
    dependencies: []

  - name: generate_seo
    dependencies: [validate]

  - name: generate_recommendations
    dependencies: [validate]

  - name: assess_reading_level
    dependencies: [validate]

  - name: score_quality
    dependencies: [generate_seo, generate_recommendations, assess_reading_level]
```

**How matching works:** All three parallel branches share the same `parent_target_id` (the `target_id` of the `validate` action). When `score_quality` runs, it pairs the records of the branches by a shared key. The key is the first of `version_correlation_id`, `source_guid`, `root_target_id` and `parent_target_id` that every record holds. For a plain diamond, that key is `source_guid`. The merged record takes its `parent_target_id` from the record of the first branch.

### Accessing Parallel Outputs

In the prompt of your merge action, use namespaced field references:

```yaml
- name: score_quality
  dependencies: [generate_seo, generate_recommendations, assess_reading_level]
  prompt: |
    SEO Keywords: {{ generate_seo.primary_keywords }}
    Similar Books: {{ generate_recommendations.similar_books }}
    Reading Level: {{ assess_reading_level.reading_level }}

    Score the overall quality of this enriched catalog entry.
```

## Map-Reduce Pattern

Use this pattern to split a document into chunks, process each chunk, and then aggregate the results:

```yaml
actions:
  - name: chunk_document
    kind: tool
    impl: chunk_document

  - name: process_chunk
    dependencies: [chunk_document]

  - name: aggregate_results
    dependencies: [process_chunk]
    kind: tool
    impl: aggregate_results
```

**How matching works:** Each chunk that a tool writes takes a new `target_id` and a new `source_guid`. The `target_id` of the input record becomes its `parent_target_id`. A tool downstream of the first action passes the `root_target_id` of the input to every chunk. Thus all chunks of one record share that `root_target_id`. A tool that is the first action, as `chunk_document` is here, writes root records. Its chunks have no `root_target_id`, and the downstream records take the `target_id` of each chunk as their root.

## Ensemble/Voting Pattern

Run the same input through multiple models. Then select or combine the answers that have the highest quality:

```yaml
actions:
  - name: prepare

  - name: gpt4_answer
    dependencies: [prepare]
    model_vendor: openai

  - name: claude_answer
    dependencies: [prepare]
    model_vendor: anthropic

  - name: gemini_answer
    dependencies: [prepare]
    model_vendor: gemini

  - name: best_answer
    dependencies: [gpt4_answer, claude_answer, gemini_answer]
```

All three model responses share the same `parent_target_id`. `best_answer` receives them merged into one record for comparison.

## Conditional Merge

Use this pattern when guards may skip some branches:

```yaml
actions:
  - name: classify

  - name: fast_path
    dependencies: [classify]
    guard:
      condition: "classify.complexity == 'low'"
      on_false: skip

  - name: slow_path
    dependencies: [classify]
    guard:
      condition: "classify.complexity == 'high'"
      on_false: skip

  - name: combine
    dependencies: [fast_path, slow_path]
```

Both guards set `on_false: skip`. Under `filter`, the default for a condition guard, a record that either branch filters never gets to `combine`. Each record passes one branch and is filtered by the other branch. Thus the merge receives no record at all. See [Filtered records leave only what is below the filter](../execution/guards.md#filtered-records-leave-only-what-is-below-the-filter).

**Handling skipped branches:** Under `skip`, the merge action still receives the record. The branch that skipped the record holds no output for that record. Thus `{% if fast_path %}` is false for that record. Your template should handle this case gracefully:

:::warning[CAUTION]
On root records (records with no parent), `parent_target_id` is **absent** from the JSON object. It is not `null`. Always use a presence check (`"parent_target_id" in record`), not a null check (`record["parent_target_id"] is None`). A null check will raise `KeyError` on root records.
:::

```yaml
- name: combine
  dependencies: [fast_path, slow_path]
  prompt: |
    {% if fast_path %}Fast result: {{ fast_path.result }}{% endif %}
    {% if slow_path %}Slow result: {{ slow_path.result }}{% endif %}
```

## FILE-Mode Lineage

FILE-mode tools receive all records at one time. The framework tracks the identity of each record through the tool with `source_index`. This design is based on the [Apache NiFi FlowFile model](https://nifi.apache.org/docs/nifi-docs/html/nifi-in-depth.html), where every record carries an immutable UUID through every processor.

**How it works:**

1. Each input record carries its identity from the upstream action.
2. The tool receives one record for each input record, with the observed fields of that record. The tool returns these records.
3. The framework matches each output to its input by `source_index`.
4. Matched outputs extend the lineage chain of the parent.
5. Outputs that declare `source_index: None` (aggregation results) get new lineage.
6. An output that gathers every record of the file that was split from one source, and only those records, takes the `source_guid` of that source. See [Output Processing](../execution/granularity.md#output-processing).
7. Any other output that names several inputs keeps the identity of the first input. It lists the other inputs under `folded_sources`. These inputs have no row of their own downstream of the tool. A fan-in beside another branch makes them `unprocessed` with reason `consumed_into_another_record`.

```
Input records:                        Tool output:                     After enrichment:
┌──────────────────────┐              ┌──────────────────────┐         ┌──────────────────────┐
│ node_id: flatten_q0  │──── kept ───▶│ node_id: flatten_q0  │────────▶│ lineage: [...,       │
│ content: {q: "Q0"}   │              │ content: {q: "Q0"}   │         │   flatten_q0,        │
└──────────────────────┘              └──────────────────────┘         │   dedup_tool_0]      │
┌──────────────────────┐                                               └──────────────────────┘
│ node_id: flatten_q1  │──── dropped (not in output)
│ content: {q: "Q1"}   │
└──────────────────────┘
┌──────────────────────┐              ┌──────────────────────┐         ┌──────────────────────┐
│ node_id: flatten_q2  │──── kept ───▶│ node_id: flatten_q2  │────────▶│ lineage: [...,       │
│ content: {q: "Q2"}   │              │ content: {q: "Q2"}   │         │   flatten_q2,        │
└──────────────────────┘              └──────────────────────┘         │   dedup_tool_1]      │
                                                                       └──────────────────────┘
```

Downstream actions can use `context_scope.observe` to load data from any ancestor in the lineage chain. The reason is that each record traces back to the correct parent, not to a shared fallback.

## What a Record Carries

A record carries the namespace of every action upstream of it through `dependencies`. Thus an action names only those actions in its `context_scope`, prompt or guard. Pre-flight refuses any other name, for example an action that runs beside it or after it, or an action on a parallel branch. Such an action is not certain to be on the records that the referring action reads. To read such an action, add it to `dependencies` (the fan-in pattern). Or, add a dependency on an action downstream of it.

## Debugging Lineage

The store keeps records compressed. Thus read them with [`agac records`](../cli/records), not with sqlite3.

### Inspect Record Ancestry

Every record carries `source_guid`, `target_id` and `lineage`. Records downstream of the first action also carry `parent_target_id` and `root_target_id`:

```bash
agac records -w <workflow> -a merge
```

### Verify Sibling Relationships

Check that parallel branches share the same parent:

```bash
# All three should print the same parent_target_id
for branch in branch_a branch_b branch_c; do
  agac records -w <workflow> -a "$branch" --field parent_target_id
done
```

### Trace Root Ancestry

For Map-Reduce with a splitting tool downstream of the first action, make sure that all chunks of one record trace back to the same root:

```bash
agac records -w <workflow> -a process_chunk --field root_target_id
# Every value for chunks of one record should be the same UUID
```

## See Also

- [Design Patterns](../../guides/design-patterns.md) — Workflow patterns that ancestry enables
- [Output Format](./output-format.md) — Complete output structure
- [Context Scope](../context/context-scope.md) — Control which data actions can see
