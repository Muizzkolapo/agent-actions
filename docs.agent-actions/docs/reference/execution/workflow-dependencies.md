---
title: Workflow Dependencies
sidebar_position: 6
---

# Workflow Dependencies

Workflow dependencies enable orchestration across multiple workflows, creating multi-stage pipelines.

## Dependency Patterns

| Pattern | Behavior |
|---------|----------|
| **Single** | Output becomes input |
| **Parallel Branches** | Outputs **merged** into combined records |
| **Fan-in** | All available, **matched by lineage** |
| **Aggregation** | All outputs **merged** and grouped by `reduce_key` |

### Single Dependency

```yaml
- name: validate_data
  dependencies: extract_data
```

### Parallel Branches

Created using `versions` - multiple executions of the same action that get merged downstream:

```yaml
# Step 1: Create parallel branches with versions
- name: research
  dependencies: [analyze_issue]
  intent: "Research the issue from different angles"
  versions:
    range: [1, 3]      # Creates research_1, research_2, research_3
    mode: parallel
  schema: support_resolution/research_findings
  prompt: $support_resolution.Research_Issue
  context_scope:
    observe:
      - analyze_issue.*
      - source.*

# Step 2: Consume parallel branches - outputs are MERGED
- name: synthesize
  dependencies: [research]  # Automatically resolves to [research_1, research_2, research_3]
  intent: "Synthesize research findings"
  context_scope:
    observe:
      - research.*  # All branches merged and available
```

### Fan-in (Multiple Different Actions)

Different actions converging - all available matched by lineage:

```yaml
# Three different analysis actions run in parallel
- name: analyze_sentiment
  dependencies: [extract_data]
  # ...

- name: analyze_entities
  dependencies: [extract_data]
  # ...

- name: analyze_topics
  dependencies: [extract_data]
  # ...

# Fan-in: all three available, matched by lineage
- name: generate_report
  dependencies: [analyze_sentiment, analyze_entities, analyze_topics]
  context_scope:
    observe:
      - analyze_sentiment.*
      - analyze_entities.*
      - analyze_topics.*
```

The first dependency determines execution count. Use `primary_dependency` to override:

```yaml
primary_dependency: analyze_entities  # analyze_entities determines execution count
```

### Aggregation

Merge ALL outputs from different actions and group by a key. Use `reduce_key`:

```yaml
# Three validators each produce validation results
- name: validator_grammar
  dependencies: [generate_content]
  # ...

- name: validator_accuracy
  dependencies: [generate_content]
  # ...

- name: validator_style
  dependencies: [generate_content]
  # ...

# Aggregation: merge ALL outputs, group by content_id
- name: aggregate_validations
  dependencies: [validator_grammar, validator_accuracy, validator_style]
  reduce_key: content_id  # Groups all validations for same content
  context_scope:
    observe:
      - validator_grammar.*
      - validator_accuracy.*
      - validator_style.*
```

**Fan-in vs Aggregation:**
- **Fan-in** (no `reduce_key`): First dep drives execution, others matched by lineage
- **Aggregation** (`reduce_key` set): All outputs merged, grouped by key

:::info Auto-Inferred Dependencies
Actions referenced in `context_scope` but not in `dependencies` are automatically available via lineage matching.
:::

## Cross-Workflow Dependencies

```yaml
actions:
  - name: process_upstream_output
    dependencies:
      - workflow: upstream_workflow
        action: final_action
```

### All Outputs from Workflow

```yaml
dependencies:
  - workflow: data_preparation
  # Receives outputs from all terminal actions
```

### Specific Action

```yaml
dependencies:
  - workflow: data_preparation
    action: validated_output
```

## CLI Execution

```bash
# Run upstream workflows first
agac run -a my_workflow --upstream

# Run downstream workflows after
agac run -a my_workflow --downstream

# Full chain execution
agac run -a my_workflow --upstream --downstream
```

| Command | What Executes |
|---------|---------------|
| `agac run -a B` | B only |
| `agac run -a B --upstream` | A → B |
| `agac run -a B --downstream` | B → C |
| `agac run -a B --upstream --downstream` | A → B → C |

## Field References

Reference upstream workflow outputs in prompts:

```yaml
- name: enhance_content
  dependencies:
    - workflow: qanalabs_quiz_gen
      action: format_quiz_text
  prompt: |
    Enhance: {{ format_quiz_text.question }}
```

## See Also

- [run Command](../cli/run) - `--upstream` and `--downstream` flags
- [Field References](../context/field-references) - Referencing upstream outputs
- [Guards](./guards) - Conditional execution
