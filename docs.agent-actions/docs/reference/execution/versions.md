---
title: Version Actions
sidebar_position: 7
---

# Version Actions

Version actions generate multiple agent instances from a single configuration, enabling parallel processing with different parameters.

## Configuration

```yaml
actions:
  - name: extract_raw_qa
    versions:
      param: i              # Loop variable name (default: i)
      range: [1, 3]         # Inclusive range - creates _1, _2, _3
      mode: parallel        # or "sequential"
    prompt: |
      Extract questions using strategy {{ i }}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `param` | string | `i` | Variable name for loop counter |
| `range` | array | Required | `[start, end]` - inclusive range |
| `mode` | string | `parallel` | `parallel` or `sequential` |

## Template Variables

| Variable | Description |
|----------|-------------|
| `{{ i }}` | Current iteration value |
| `{{ idx }}` | Zero-based index |
| `{{ loop.length }}` | Total iterations |
| `{{ loop.first }}` | True on first iteration |
| `{{ loop.last }}` | True on last iteration |

## Version Consumption

Downstream actions consume outputs from all version iterations:

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
      - extract_raw_qa.*  # Wildcard reference
```

Outputs are merged as nested namespaces:

```json
{
  "extract_raw_qa_1": {"questions": ["Q1a", "Q1b"]},
  "extract_raw_qa_2": {"questions": ["Q2a", "Q2b"]},
  "extract_raw_qa_3": {"questions": ["Q3a", "Q3b"]}
}
```

Access in prompts:

```yaml
prompt: |
  Strategy 1: {{ extract_raw_qa_1.questions }}
  Strategy 2: {{ extract_raw_qa_2.questions }}
```

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
- [Workflow Dependencies](./workflow-dependencies) - Dependency patterns
