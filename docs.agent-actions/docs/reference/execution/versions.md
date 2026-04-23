---
title: Version Actions
sidebar_position: 7
---

# Version Actions

Version actions generate multiple action instances from a single configuration, enabling parallel processing with different parameters.

## Configuration

```yaml
actions:
  - name: extract_raw_qa
    versions:
      range: [1, 3]         # Inclusive range - creates _1, _2, _3
      mode: parallel        # or "sequential"
    prompt: |
      Extract questions using strategy {{ i }}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `range` | array | Required | `[start, end]` - inclusive range |
| `mode` | string | `parallel` | `parallel` or `sequential` |

## Template Variables

Version variables are available in both inline prompts and prompt store references:

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `{{ i }}` | int | Current iteration value | `1`, `2`, `3` |
| `{{ idx }}` | int | Zero-based index | `0`, `1`, `2` |
| `{{ version.length }}` | int | Total iterations | `3` |
| `{{ version.first }}` | bool | True on first iteration | `true`/`false` |
| `{{ version.last }}` | bool | True on last iteration | `true`/`false` |
| `{{ custom_param }}` | int | Custom param value (when `param` is set) | `1`, `2`, `3` |

### Custom Parameter Names

When using a custom `param` name, it's available as a top-level variable:

```yaml
versions:
  param: classifier_id
  range: [1, 3]
```

```jinja2
{# Both work: #}
Classifier {{ classifier_id }}
Classifier {{ i }}
```

## Using with Prompt Store

Version variables work with prompt store references, enabling reusable versioned prompts:

```yaml
# In workflow config
- name: classify_severity
  versions:
    range: [1, 3]
    mode: parallel
  prompt: $incident_triage.Classify_Severity
```

```markdown
{# In prompt_store/incident_triage.md #}

{prompt Classify_Severity}
You are classifier {{ i }} of {{ version.length }}.

{% if version.first %}
Be conservative in your assessment.
{% elif version.last %}
Be comprehensive and thorough.
{% else %}
Balance precision and recall.
{% endif %}

Analyze the incident and provide your classification.
{end_prompt}
```

This renders as:
- **Classifier 1**: "You are classifier 1 of 3. Be conservative..."
- **Classifier 2**: "You are classifier 2 of 3. Balance precision..."
- **Classifier 3**: "You are classifier 3 of 3. Be comprehensive..."

## Version Consumption

Downstream actions consume outputs from all version iterations. The `version_consumption` block controls how versioned outputs are collected.

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Name of the upstream versioned action to consume |
| `pattern` | string | `merge` — combine all version outputs into one record (fan-in); `match` — pair each version output 1:1 with the consumer |

### merge (Fan-In)

The most common pattern. All version outputs are collected into a single record, keyed by version name (e.g., `score_quality_1`, `score_quality_2`). Use this for aggregation, voting, and consensus:

```yaml
- name: score_quality
  versions:
    range: [1, 3]

- name: aggregate_scores
  dependencies: [score_quality]
  version_consumption:
    source: score_quality
    pattern: merge
  context_scope:
    observe:
      - score_quality.*  # Wildcard reference
```

Outputs are merged as nested namespaces:

```json
{
  "score_quality_1": {"overall_score": 8, "confidence": 0.9},
  "score_quality_2": {"overall_score": 7, "confidence": 0.85},
  "score_quality_3": {"overall_score": 9, "confidence": 0.95}
}
```

Access in prompts (LLM actions):

```yaml
prompt: |
  Scorer 1: {{ score_quality_1.overall_score }}
  Scorer 2: {{ score_quality_2.overall_score }}
```

Access in tool UDFs (FILE mode):

```python
# Each version is a nested namespace in content
scorer_1 = content["score_quality_1"]
scorer_2 = content["score_quality_2"]

# Iterate all versions dynamically
scores = []
for key, data in content.items():
    if key.startswith("score_quality_") and isinstance(data, dict):
        scores.append(data["overall_score"])
```

When observe uses wildcards (`score_quality.*`), fields are also expanded as qualified flat keys (`score_quality_1.overall_score`, `score_quality_2.overall_score`) alongside the nested dicts. Both access patterns work.

## Common Patterns

### Multi-Strategy Extraction

```yaml
- name: extract_with_strategies
  versions:
    range: [1, 3]
  prompt: |
    {% if i == 1 %}Focus on explicit statements
    {% elif i == 2 %}Focus on implicit meanings
    {% else %}Focus on contextual clues{% endif %}

    Extract from: {{ source.text }}

- name: combine_extractions
  dependencies: [extract_with_strategies]
  version_consumption:
    source: extract_with_strategies
    pattern: merge
```

### Sequential Refinement

```yaml
- name: refine_iteration
  versions:
    range: [1, 3]
    mode: sequential
  dependencies:
    - "{% if i == 1 %}draft_content{% else %}refine_iteration_{{ i-1 }}{% endif %}"
```

### Parallel Model Comparison

```yaml
- name: model_comparison
  versions:
    range: [1, 3]
  model_vendor: |
    {% if i == 1 %}openai{% elif i == 2 %}anthropic{% else %}google{% endif %}
```

## Execution Modes

**Parallel (default)**: All iterations run simultaneously. Use when iterations are independent.

**Sequential**: Iterations run one at a time. Use when later iterations depend on earlier ones or to control API rate limits.

## Context Scope with Versions

```yaml
- name: extract_variants
  versions:
    range: [1, 3]

- name: analyze
  dependencies: [extract_variants]
  context_scope:
    observe:
      - extract_variants.*  # Expands to all version namespaces
```

Reference specific iterations:

```yaml
context_scope:
  observe:
    - extract_variants_1.specific_field
    - extract_variants_2.specific_field
```

## Debugging

Inspect expanded version actions:

```bash
agac inspect -a workflow_name
```

Enable prompt debug to see rendered prompts per iteration:

```yaml
- name: extract_variants
  versions:
    range: [1, 3]
  prompt_debug: true
```

## See Also

- [Context Scope](../context/context-scope) - Field flow control
- [Field References](../context/field-references) - Accessing version outputs
