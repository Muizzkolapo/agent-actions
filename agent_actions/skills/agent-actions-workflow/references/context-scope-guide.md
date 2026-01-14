# Context Scope Guide

Context Scope controls the visibility and flow of data between actions.

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

Include fields in LLM context. When specified, **only listed fields** are visible.

```yaml
- name: Cluster_Validation_Agent
  dependencies: [group_by_similarity, cluster_list]
  context_scope:
    observe:
      - canonicalize_facts.candidate_facts_list
      - cluster_list.semantic_unique_id
      - group_by_similarity.num_similar_facts
```

**Use cases:**
- Focus LLM attention on specific fields
- Reduce context size
- Ensure consistent data visibility

## Drop Directive

Exclude fields from LLM context. All other fields included unless `observe` is specified.

```yaml
- name: fact_extractor
  context_scope:
    drop:
      - source.syllabus    # Not needed for extraction
      - source.url
```

**Use cases:**
- Remove noisy/irrelevant fields
- Exclude internal/debugging fields
- Hide sensitive data

## Passthrough Directive

Forward fields to output **without** including in LLM context.

```yaml
- name: Cluster_Validation_Agent
  context_scope:
    observe:
      - canonicalize_facts.candidate_facts_list
    passthrough:
      - group_by_similarity.grouped_facts   # Forward without LLM seeing
```

**Use cases:**
- Preserve metadata for downstream
- Forward fields that shouldn't influence LLM
- Maintain data lineage

## Seed Data

Load static reference data:

```yaml
defaults:
  context_scope:
    seed_data:
      exam_syllabus: $file:mcp_qanalabs_syllabus.json

actions:
  - name: extract_facts
    prompt: |
      Using syllabus: {{ seed.exam_syllabus.exam_name }}
      Extract facts from: {{ source.page_content }}
```

Seed data is **prompt-only**. It is available under the `seed` namespace for
template rendering, but it is not injected into LLM/tool context by default.

| Syntax | Description |
|--------|-------------|
| `$file:path.json` | Load JSON from seed_data directory |
| `$file:path.yaml` | Load YAML from seed_data directory |

## Resolution Order

1. **Observe filter** - If specified, start with only those fields
2. **Drop filter** - Remove any fields in drop list
3. **Passthrough merge** - After LLM processing, merge passthrough into output

## Best Practices

### Use Observe for Focus

```yaml
# Good: Explicit about what LLM sees
context_scope:
  observe:
    - extract.facts
    - source.title

# Avoid: Including everything when only some matter
# (no context_scope)
```

### Use Drop for Noise Reduction

```yaml
context_scope:
  drop:
    - upstream.debug_info
    - upstream.internal_metrics
```

### Use Passthrough for Data Lineage

```yaml
context_scope:
  passthrough:
    - source.record_id      # For tracking
    - extract.timestamp     # For ordering
```

### Combine Directives Strategically

```yaml
- name: generate_feynman_explanation
  context_scope:
    observe:
      - generate_summary.summary              # LLM needs this
    passthrough:
      - generate_scenarios.question           # Forward to output
      - generate_scenarios.answer
      - source.url                            # Preserve source
    drop:
      - reconstruct_options.thinking_process_1  # Internal
```

## Complex Passthrough Chain

Chain data through multiple actions:

```yaml
- name: score_question_quality
  context_scope:
    observe:
      - source.referenced_in
    passthrough:
      - generate_scenarios.question
      - generate_scenarios.options
      - generate_scenarios.answer

- name: suggest_distractor_counts
  dependencies: [filter_low_quality_questions]
  context_scope:
    passthrough:
      - generate_scenarios.question     # Continues from previous
      - generate_scenarios.options
      - generate_scenarios.answer
```

## Debugging

Enable `prompt_debug` to see what context the LLM receives:

```yaml
- name: my_action
  prompt_debug: true
  context_scope:
    observe:
      - upstream.data
```

## Error Handling

**Missing Field in Observe:**
```
ConfigurationError: Field 'nonexistent_action.field' in observe not found
```
Ensure the referenced action exists and produces the field.

**Invalid Passthrough Source:**
```
ConfigurationError: Cannot passthrough from action 'future_action' -
  action is not an upstream dependency
```
You can only passthrough from actions that are dependencies.
