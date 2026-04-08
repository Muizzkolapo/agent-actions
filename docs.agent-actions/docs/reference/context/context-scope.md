---
title: Context Scope
sidebar_position: 3
---

# Context Scope

Context Scope controls data visibility and flow between actions—what the LLM sees, what passes through to output, and what gets excluded.

:::warning Required
`context_scope` is **required** on every action. Omitting it raises a `ConfigurationError`. Every action must declare its data dependencies explicitly via `observe`, `passthrough`, or `drop`.
:::

## Directives

| Directive | Purpose | In LLM Context | In Output |
|-----------|---------|----------------|-----------|
| `observe` | Include specific fields in LLM context | Yes | No |
| `drop` | Exclude specific fields from context | No | No |
| `passthrough` | Forward fields directly to output | No | Yes |

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

The `observe` directive explicitly includes fields in the LLM context. When specified, only listed fields are visible to the LLM.

```yaml
- name: Cluster_Validation_Agent
  dependencies: [group_by_similarity, cluster_list]
  context_scope:
    observe:
      - canonicalize_facts.candidate_facts_list
      - cluster_list.semantic_unique_id
      - group_by_similarity.num_similar_facts
      - source.page_content  # Can include source data
```

## Drop Directive

The `drop` directive excludes fields from the LLM context. All other fields are included unless `observe` is also specified.

```yaml
- name: fact_extractor
  context_scope:
    drop:
      - source.syllabus    # Reference data not needed
      - source.url         # URL not relevant
```

## Passthrough Directive

The `passthrough` directive forwards fields directly to the action output **without** including them in the LLM context. Data flows around the LLM rather than through it.

```yaml
- name: Cluster_Validation_Agent
  context_scope:
    observe:
      - canonicalize_facts.candidate_facts_list
    passthrough:
      - group_by_similarity.grouped_facts   # Forward without LLM seeing
      - source.url                          # Preserve for downstream
```

## Seed Data

Static reference data can be loaded via `seed_path`. See [Seed Data](./seed-data.md) for details.

```yaml
defaults:
  context_scope:
    seed_path:
      exam_syllabus: $file:syllabus.json
```

## Version Field Patterns

When consuming outputs from version actions, field names are prefixed to avoid collisions. Use wildcard syntax to reference all iterations:

```yaml
- name: extract_raw_qa
  versions:
    range: [1, 3]

- name: flatten_questions
  dependencies: [extract_raw_qa]
  context_scope:
    observe:
      - extract_raw_qa.*  # Matches extract_raw_qa_1_*, extract_raw_qa_2_*, etc.
```

See [Version Actions](../execution/versions) for complete documentation.

## Auto-Inferred Context Dependencies

Actions referenced in `context_scope` but **not** in `dependencies` are automatically treated as **context dependencies**. These are loaded via the historical loader with lineage matching.

```yaml
- name: generate_report
  dependencies: [extract_data]  # Primary input source
  context_scope:
    observe:
      - extract_data.*         # From input files
      - enrich_data.*          # Auto-inferred: loaded via historical loader
      - validate_data.*        # Auto-inferred: loaded via historical loader
```

**How it works:**
1. `extract_data` is in `dependencies` → its output files are processed as input
2. `enrich_data` and `validate_data` are only in `context_scope` → auto-inferred as context dependencies
3. Context dependencies are loaded via the historical loader, matched by **lineage** to ensure data from the same record flow

This is especially useful for **fan-in patterns** where multiple upstream actions feed into one action:

```yaml
- name: final_action
  dependencies: [action_A, action_B, action_C]  # Fan-in pattern
  context_scope:
    observe:
      - action_A.*   # Primary input (first in list)
      - action_B.*   # Context dependency (lineage-matched)
      - action_C.*   # Context dependency (lineage-matched)
```

See [Workflow Dependencies](../execution/workflow-dependencies) for details on fan-in, parallel, and aggregation patterns.

## Resolution Order

1. **Observe filter** - If `observe` is specified, start with only those fields
2. **Drop filter** - Remove any fields in `drop` list
3. **Passthrough merge** - After LLM processing, merge passthrough fields into output

Passthrough fields never enter the LLM context—they join the output after processing.

## Best Practices

1. **Use observe for focus**: When LLM needs only specific fields
2. **Use drop for noise reduction**: When most fields are needed but some aren't
3. **Use passthrough for data lineage**: Preserve data that downstream actions need

### Combined Example

```yaml
- name: generate_explanation
  context_scope:
    observe:
      - generate_summary.summary    # LLM needs this
    passthrough:
      - source.url                  # Preserve for downstream
    drop:
      - upstream.debug_info         # Internal, not needed
```

## Debugging Context

Enable `prompt_debug` to see the rendered context:

```yaml
- name: my_action
  prompt_debug: true
```

## See Also

- [Version Actions](../execution/versions) - Loop configuration and consumption patterns
- [Field References](./field-references) - Field reference syntax and validation
- [Seed Data](./seed-data) - Loading static reference data
- [Workflow Dependencies](../execution/workflow-dependencies) - Dependency patterns
