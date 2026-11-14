---
title: Context Scope
sidebar_position: 3
---

# Context Scope

Context scope controls which data an action can see and how data flows between actions. It selects the upstream namespaces that an action can read from the record. It also selects the fields that pass through to the output and the fields that are excluded.

:::warning[CAUTION]
**Required:** `context_scope` is **required** on each action. If you omit it, pre-flight fails with `Action '<name>' has no context_scope. All actions must declare data dependencies via context_scope.`. Each action must declare its data dependencies explicitly with `observe`, `passthrough` or `drop`.

Many examples in these docs show a single key and omit `context_scope` to keep the example short. These examples are fragments, not complete actions. When you copy one into a workflow, add a `context_scope`.
:::

## Directives

| Directive | Purpose | In LLM Context | In Output |
|-----------|---------|----------------|-----------|
| `observe` | Adds specific fields to the LLM context | Yes | No |
| `drop` | Removes fields that `observe` added to the context | No | No |
| `passthrough` | Sends fields directly to the output | No | Yes |

## Syntax

```yaml
context_scope:
  observe:
    - upstream_action.field_name
    - another_action.nested.field
  drop:
    - source.unused_field
    - upstream_action.internal_field
  passthrough:
    - upstream_action.preserve_this
    - source.metadata
```

## Observe Directive

The `observe` directive selects the upstream namespaces and fields that the action can see. The LLM context contains only the listed fields.

```yaml
- name: Cluster_Validation_Agent
  dependencies: [canonicalize_facts, group_by_similarity, cluster_list]
  context_scope:
    observe:
      - canonicalize_facts.candidate_facts_list
      - cluster_list.semantic_unique_id
      - group_by_similarity.num_similar_facts
      - source.content  # Can include source data
```

## Drop Directive

The `drop` directive removes fields that `observe` selected from the context. Usually `observe` selects these fields with a wildcard, for example `source.*`. `drop` adds nothing. An action with only `drop` has no `source` namespace in its context, and a prompt that reads `source` fails.

```yaml
- name: fact_extractor
  context_scope:
    observe:
      - source.*
    drop:
      - source.syllabus    # Reference data not needed
      - source.url         # URL not relevant
```

## Passthrough Directive

The `passthrough` directive sends fields directly to the action output. It does **not** add them to the LLM context. The data goes around the LLM, not through it.

```yaml
- name: Cluster_Validation_Agent
  dependencies: [canonicalize_facts, group_by_similarity]
  context_scope:
    observe:
      - canonicalize_facts.candidate_facts_list
    passthrough:
      - group_by_similarity.grouped_facts   # Forward without LLM seeing
      - source.url                          # Preserve for downstream
```

:::warning[CAUTION]
**Passthrough keeps the field in the output. It does not add the field to the downstream context.**

`passthrough` keeps a field in **the output record of this action** (for lineage or export). It does **not** make that field available to downstream actions _through_ this action. If a downstream action needs the value, it must `observe` the value from its **original producing action** (for example `observe: [source.url]`). It must not observe the value from the action that passed it through.

In particular, `observe: [some_action.*]` expands only to the output fields of `some_action`. It does **not** add the fields that `some_action` only passed through. An upstream `passthrough` does not satisfy a downstream `observe`. A wildcard leaves the passed-through field out of the context. An explicit `observe: [some_action.url]` is refused before the run.

A passed-through field is stored under the namespace that it came from. It is not stored under the action that passed it through. For example, after `passthrough: [source.url]` on `summarize`, the field is `source.url`. Pre-flight refuses a prompt, `observe` or `passthrough` that reads `summarize.url`. Pre-flight also refuses one that reads a field that `summarize` only observes. It refuses these fields in the same way that it refuses a field that the schema of the action does not list.
:::

## Seed Data

You can load static reference data with `seed`. See [Seed Data](./seed-data.md) for details.

```yaml
defaults:
  context_scope:
    seed:
      exam_syllabus: $file:syllabus.json
  data_source:
    type: local
    folder: ./staging
    file_type: [json]
  expect:
    repair: auto
    max_iterations: 3
  batch_max_workers: 6
```

:::note
`data_source`, `expect` and `batch_max_workers` are workflow-level defaults. They can also occur in the `defaults:` block. [Defaults](../configuration/defaults.md) and [Run Modes](../execution/run-modes.md) give the documentation for these keys.
:::

## Version Field Patterns

Each iteration of a version action keeps its output in a separate namespace. The name of the namespace contains the iteration number (`extract_raw_qa_1`, `extract_raw_qa_2`). A consumer declares `version_consumption` and uses the wildcard syntax to refer to all iterations:

```yaml
- name: extract_raw_qa
  versions:
    range: [1, 3]

- name: flatten_questions
  dependencies: [extract_raw_qa]
  version_consumption:
    source: extract_raw_qa
    pattern: merge
  context_scope:
    observe:
      - extract_raw_qa.*  # Matches the namespaces extract_raw_qa_1, extract_raw_qa_2, ...
```

See [Version Actions](../execution/versions) for the complete documentation.

## Auto-Inferred Context Dependencies

If an action is in `context_scope` or in the prompt but **not** in `dependencies`, it is automatically a **context dependency**. A context dependency is read from the record. The record carries the namespace of each action upstream of it. Thus a context dependency must be upstream of the action through its `dependencies`.

```yaml
- name: extract_data
- name: enrich_data
  dependencies: [extract_data]
- name: validate_data
  dependencies: [enrich_data]

- name: generate_report
  dependencies: [validate_data]  # Input source
  context_scope:
    observe:
      - validate_data.*        # From input files
      - enrich_data.*          # Upstream of validate_data
      - extract_data.*         # Upstream of enrich_data
```

**How it works:**
1. `validate_data` is in `dependencies`. Thus its output files are processed as input.
2. `enrich_data` and `extract_data` are only in `context_scope`. They are upstream of `validate_data`. Thus pre-flight accepts them without a `dependencies` entry.
3. Context dependencies are read from the namespaces on each input record. Thus the data comes from the same record.

Pre-flight refuses an action that names a context dependency that is not upstream of it.
Examples are an action that runs beside it or after it, and an action on a parallel branch.
The namespace of that context dependency is not certain to be on the records that the action reads.
To read the namespace, add a dependency on an action downstream of the context dependency.
Or, also add a dependency on the context dependency itself. This is the **fan-in pattern**,
where multiple upstream actions send data into one action:

```yaml
- name: final_action
  dependencies: [action_A, action_B, action_C]  # Fan-in pattern
  context_scope:
    observe:
      - action_A.*   # Fan-in dependency
      - action_B.*   # Fan-in dependency
      - action_C.*   # Fan-in dependency
```

Each dependency is an input. For the same source record, the outputs of `action_A`, `action_B` and `action_C` are merged into one record. `final_action` runs one time for each merged record. The order of the list has no effect.

This table shows how the records of the branches pair:

| Branches | What `final_action` runs on |
|----------|-----------------------------|
| Each branch returns one record for each input | One merged record for each source record |
| One branch returns several records for each input (a tool that splits a record). The other branches return one record. | One merged record for each split record. Each merged record has the record of the other branches for its source. |
| One branch splits a record. Another branch splits the records of that branch again (it reads the first branch). The other branches return one record. | One merged record for each record of the second split. Each merged record has the record of the first split that it came from. It also has the record of the other branches for its source. |
| All branches read one earlier split (an action upstream of all branches returned several records for each input) | One merged record for each record of that split |
| One branch splits a record, and a `granularity: File` tool below it gathers all records of that split back into one record | The result is the same as if that branch did not split. The gathered record is the record of the source. |
| Two or more branches each hold their own split of the same source record. Or, one branch splits a source beside branches that read an earlier split of that source. | Nothing. The action fails and names the branches and the source record. |
| One branch holds a record that a `granularity: File` tool returned with `source_index: None` (an aggregate, marked `aggregated_by`). Another branch does not read that aggregate. | Nothing. The action fails and names the branches and the action of the tool. If each branch reads the aggregate, the aggregate pairs like any record. |
| One branch has no record, because its `granularity: File` tool folded the record into the row of another record (a `source_index` list such as `[a, b]`). The row lists `b` under `folded_sources`. | One merged record for `b`, `unprocessed` with reason `consumed_into_another_record`. Its tombstone names the row that it went into as `metadata.consumed_into`. `a` merges with the folded row as usual. |
| One branch holds a tombstone for a source. For example, a record for which its `granularity: File` tool returned no row. | One merged record for that source, `unprocessed`. The action below skips that record. |

A record of one split is not a record of another split. Thus two splits of one source
have no pairing that keeps the fields of each branch. The action fails. It does not run on
records that hold one branch with empty fields for the other branches. The action also fails
when a branch splits a source and keeps one record of the split. An example is a split behind
a guard that filters the other records.

To read the records of two branches for each split, split the source one time, in an action
upstream of the two branches. Then make each branch read that action. If you do not need
this, let a maximum of one branch split the source. Or, gather the split of a branch back
into one record for each source.

A `granularity: File` tool gathers a split when these two conditions are true:

- One output names, in its `source_index` list, each record of its file that was split from one source, and nothing else.
- No other output names any of these records.

That output takes the identity of the source (`source_guid`), in the same way that a
record that was never split holds it. Thus the output pairs like a record that was never
split. An output that gathers records of several sources, or only some records of a split,
keeps the identity of the first record that it names. See [Granularity](../execution/granularity.md#output-processing).

## Resolution Order

1. **Observe filter** - Start with only the fields that `observe` lists.
2. **Drop filter** - Remove the fields that are in the `drop` list.
3. **Passthrough merge** - After the LLM processing, merge the passthrough fields into the output.

Passthrough fields never go into the LLM context. They join the output after the processing.

## Best Practices

1. **Use observe for focus**: Use it when the LLM needs only specific fields.
2. **Use drop to reduce noise**: Pair it with a wildcard `observe`. Use it when the action needs most fields but not all of them.
3. **Use passthrough for data lineage**: Use it to keep the data that downstream actions need.

### Combined Example

```yaml
- name: generate_explanation
  dependencies: [generate_summary]
  context_scope:
    observe:
      - generate_summary.*          # LLM needs these
    passthrough:
      - source.url                  # Preserve for downstream
    drop:
      - generate_summary.debug_info # Internal, not needed
```

## Debugging Context

Enable `prompt_debug` to print the rendered prompt and its context data:

```yaml
- name: my_action
  prompt_debug: true
```

## See Also

- [Version Actions](../execution/versions) - Loop configuration and consumption patterns
- [Field References](./field-references) - Field reference syntax and validation
- [Seed Data](./seed-data) - Loading static reference data
