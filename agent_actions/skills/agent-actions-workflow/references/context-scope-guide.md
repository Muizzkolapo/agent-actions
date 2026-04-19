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
  dependencies: group_by_similarity       # Input source
  context_scope:
    observe:
      - canonicalize_facts.candidate_facts_list   # Context (auto-inferred)
      - cluster_list.semantic_unique_id           # Context (auto-inferred)
      - group_by_similarity.num_similar_facts     # Input
```

**Note:** Actions referenced in `observe`/`passthrough` but not in `dependencies` are auto-inferred as context dependencies.

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

Static reference data loaded via `seed_data:` in the workflow config and accessed via the `seed.` prefix in templates.

**WARNING:** The config key is `seed_data:` but the runtime reference prefix is `seed.` — NOT `seed_data.`. Using `seed_data.rubric` in templates or observe directives will silently resolve to empty. This is the most common namespace mistake.

**Config key vs reference prefix:**

| Where | Syntax | Example |
|-------|--------|---------|
| Workflow YAML config | `seed_data:` | `seed_data: { syllabus: $file:syllabus.json }` |
| Prompt templates | `seed.` | `{{ seed.syllabus.exam_name }}` |

```yaml
defaults:
  context_scope:
    seed_path:
      exam_syllabus: $file:syllabus.json

actions:
  - name: extract_facts
    prompt: |
      Using syllabus: {{ seed.exam_syllabus.exam_name }}
      Extract facts from: {{ source.page_content }}
```

Seed data is **auto-available in prompts** without listing it in `observe`. It is available under the `seed` namespace for template rendering, but it is not injected into LLM/tool context by default.

When you need seed data inside a **UDF tool action**, you must explicitly list it in `observe`:

```yaml
- name: enrich_data
  kind: tool
  impl: enrich_with_syllabus
  context_scope:
    observe:
      - seed.exam_syllabus    # Required for UDF tools only
```

| Syntax | Description |
|--------|-------------|
| `$file:path.json` | Load JSON from seed_data directory |
| `$file:path.yaml` | Load YAML from seed_data directory |

## output_field (json_mode: false)

When `json_mode: false`, the LLM returns raw text instead of structured JSON. The framework wraps this text using `output_field`:

```yaml
- name: assess_severity
  json_mode: false
  output_field: severity               # Default is "raw_response"
  context_scope:
    observe: [source.*]
```

The raw text response gets wrapped as:
```json
[{"severity": "The system shows critical degradation in..."}]
```

### Downstream access

Downstream actions access `output_field` values through the normal namespace:

```yaml
- name: route_ticket
  dependencies: [assess_severity]
  context_scope:
    observe: [assess_severity.*]       # Sees assess_severity.severity
```

In prompts: `{{ assess_severity.severity }}`
In UDFs: `content.get("assess_severity", {}).get("severity", "")`

### Guards with output_field

Guard conditions see flattened field names — the `output_field` value is promoted to top-level:

```yaml
- name: escalate
  dependencies: [assess_severity]
  guard:
    condition: 'severity != "low"'     # Direct field name, not assess_severity.severity
  context_scope:
    observe: [assess_severity.*]
```

### Constraints

- `json_mode: false` and `schema` together trigger a warning — the schema is ignored at runtime since there's no JSON to validate
- `output_field` only works with `json_mode: false`
- Default `output_field` is `"raw_response"` — access as `content.get("action_name", {}).get("raw_response", "")`

## Guard Field Visibility

Guard conditions evaluate against flattened field names from observed data (see Guards section in SKILL.md for examples).

**Collision risk:** When observing from multiple upstream actions with overlapping field names, the last-loaded namespace wins. Avoid this by observing specific fields instead of wildcards when field names might collide.

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
```

> **Note:** `context_scope` is **required** on every action. Omitting it raises a `ConfigurationError` at validation time. Every action must declare its data dependencies explicitly.

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
  dependencies: generate_scenarios         # Input source
  context_scope:
    observe:
      - source.referenced_in
    passthrough:
      - generate_scenarios.question
      - generate_scenarios.options
      - generate_scenarios.answer

- name: suggest_distractor_counts
  dependencies: filter_low_quality_questions
  context_scope:
    passthrough:
      - generate_scenarios.question     # Context (auto-inferred)
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

**Invalid Action Reference:**
```
ConfigurationError: Action 'nonexistent_action' referenced in context_scope not found in workflow
```
All actions referenced in `context_scope` must exist in the workflow. They're auto-inferred as context dependencies.

**Missing agent_indices:**
```
ConfigurationError: agent_indices is required when action has dependencies
```
This error occurs during execution if `agent_indices` wasn't provided but the action has dependencies.
