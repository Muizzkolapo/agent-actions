---
title: Version Actions
sidebar_position: 7
---

# Version Actions

A version action makes many action instances from one configuration. The instances can run in parallel with different parameters.

## Configuration

```yaml
actions:
  - name: extract_raw_qa
    versions:
      range: [1, 3]         # Inclusive range - creates _1, _2, _3
    prompt: |
      Extract questions using strategy {{ i }}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `param` | string | `i` | The name of the version variable in templates |
| `range` | array | `[1, 1]` | Two integers for an inclusive `[start, end]`, or a different number of values to expand over |

A `range` with two elements is always an inclusive pair of integers. When the workflow loads, the framework refuses `[3, 1]` and a pair of non-integers. A list of one value, or of three or more values, gives the values directly as the suffixes. For example:

- `range: ["literal", "idiomatic", "formal"]` gives `translate_literal`, `translate_idiomatic` and `translate_formal`.
- `range: [5]` gives `_5`.

Version consumption cannot collect those versions. Fan-in groups versions by a numeric suffix. Thus a consumer of a non-integer range finds no versions and logs a warning. If a downstream action consumes the versions, use an integer range.

## Template Variables

Version variables are available in inline prompts and in prompt store references. There, they render for each record. In the other values of a versioned action (`model_vendor`, `model_name`, `intent`, …), they render one time for each version, when the workflow loads:

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `{{ i }}` | int | The value of the current iteration | `1`, `2`, `3` |
| `{{ idx }}` | int | The index, which starts at zero | `0`, `1`, `2` |
| `{{ version.length }}` | int | The total number of iterations | `3` |
| `{{ version.first }}` | bool | True on the first iteration | `true`/`false` |
| `{{ version.last }}` | bool | True on the last iteration | `true`/`false` |
| `{{ custom_param }}` | int | The value of the custom parameter (when `param` is set) | `1`, `2`, `3` |

### Custom Parameter Names

When you use a custom `param` name, that name is available as a top-level variable:

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

Version variables work with prompt store references. Thus you can use one versioned prompt again in many places:

```yaml
# In workflow config
- name: classify_severity
  versions:
    range: [1, 3]
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

The prompt renders as:

- **Classifier 1**: "You are classifier 1 of 3. Be conservative..."
- **Classifier 2**: "You are classifier 2 of 3. Balance precision..."
- **Classifier 3**: "You are classifier 3 of 3. Be comprehensive..."

## Version Consumption

Downstream actions consume the outputs of all version iterations. The `version_consumption` block controls how the framework collects versioned outputs.

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | The name of the upstream versioned action to consume |
| `pattern` | string | `merge` (default) — combine all version outputs into one record (fan-in). The framework accepts `match` and runs it as `merge` |

:::note
Consumption requires numeric suffixes on the versions of the source. Thus the source must have an integer `range`.
:::

### merge (Fan-In)

This pattern is the most common. The framework collects all version outputs into one record, with the version name as the key (for example, `score_quality_1`, `score_quality_2`). Use this pattern for aggregation, voting and consensus:

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

The framework merges the outputs as nested namespaces:

```json
{
  "score_quality_1": {"overall_score": 8, "confidence": 0.9},
  "score_quality_2": {"overall_score": 7, "confidence": 0.85},
  "score_quality_3": {"overall_score": 9, "confidence": 0.95}
}
```

To get the outputs in prompts (LLM actions), use this pattern:

```yaml
prompt: |
  Scorer 1: {{ score_quality_1.overall_score }}
  Scorer 2: {{ score_quality_2.overall_score }}
```

In a record tool, each version is a dict under its own name:

```python
scorer_1 = data["score_quality_1"]
scorer_2 = data["score_quality_2"]

# Iterate all versions dynamically
scores = []
for key, version in data.items():
    if key.startswith("score_quality_") and isinstance(version, dict):
        scores.append(version["overall_score"])
```

In a FILE tool, each item holds the observed fields as flat keys. Each key has the version as its prefix (`score_quality_1.overall_score`, `score_quality_2.overall_score`). The item has no nested dicts.

```python
for item in records:
    scores = [
        value
        for key, value in item.items()
        if key.startswith("score_quality_") and key.endswith(".overall_score")
    ]
```

**Other dependencies.** A merge may list dependencies other than the versioned source, for example a sibling branch of the same upstream action. The framework pairs their records with the merged versions in the same way that a fan-in pairs its branches. Thus each namespace that the merge observes from them is next to the version namespaces. This is true in prompts and in tools:

```yaml
- name: tally_verdicts
  kind: tool
  impl: tally_verdicts
  dependencies: [policy_judge, claim_judge]
  version_consumption:
    source: policy_judge
    pattern: merge
  context_scope:
    observe:
      - policy_judge.*   # policy_judge_1, policy_judge_2, ...
      - claim_judge.*    # the sibling branch, on the same record
```

The versions decide which files the merge reads. The framework reads the records of another dependency from the files that the versions hold. As in all fan-ins, the framework does not merge a record that a guard `filter` removed in one of these dependencies. A record that one of these dependencies failed is cascade-skipped.

**When the merge cannot read its versions.** The merge can fail to read its versions for two reasons:

- The store fails while the merge reads the data that its versions hold.
- The framework cannot align the records of a version with the records of the other versions.

In these cases, the merge fails in the same way as all actions fail:

1. The framework marks the merge `failed` with the reason.
2. The framework skips the actions that read the merge.
3. The actions on other branches continue to run.
4. The run ends with failures.

The next `agac run`, or `agac retry`, runs the merge again. If no version holds a record because a guard filtered all of them, the framework skips the merge. The merge does not fail.

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

### Dollar-brace substitution

All values of a versioned action support **dollar-brace substitution** (`${i}`, `${i-1}` and other expressions). The dependency strings also support it. Jinja2 version variables, for example `{{ i }}`, render in the prompt for each record. They render in the other values of the action for each version.

:::warning[CAUTION]
You cannot use `${i-1}` to make a chain from one version to the previous version. On the first version, `${i-1}` resolves to nothing. The result is a dependency on a bare `<action>_` that does not exist, and the framework refuses the workflow. A reference to the previous version through `context_scope` reports a cyclic dependency. The reason is that all versions of an action are one node in the dependency graph. No supported method makes the versions of one action run in sequence. See Execution Order below.
:::

### Parallel Model Comparison

```yaml
- name: model_comparison
  versions:
    range: [1, 3]
  model_vendor: "{% if i == 1 %}openai{% elif i == 2 %}anthropic{% else %}gemini{% endif %}"
```

Each version gets the branch for its own `i`. Set `model_name` and `api_key` in the same way. Keep such a value on one quoted line. A block scalar (`|`) adds a trailing newline to the value that it renders. `model_vendor: "openai\n"` names no vendor.

## Execution Order

Each version becomes a separate action in the dependency graph. Thus the graph sets
the order. No setting of an action changes the order.

**Independent versions run together.** When the iterations have no dependency between them, they are all
in one execution level. They run at the same time.

**You cannot set an order for the versions of one action.** By design, the versions have
the same dependencies. Thus they are in the same level, and no setting in the block
changes that level. If later work must see earlier work, use pooling, not versions.
Pooling uses separate actions. Each action can observe the actions before it.

To run all of a run in sequence, use `--execution-mode sequential`. To set a maximum
number of actions that run at the same time, use `--concurrency-limit`.

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

To refer to specific iterations, use this configuration:

```yaml
context_scope:
  observe:
    - extract_variants_1.specific_field
    - extract_variants_2.specific_field
```

## Debugging

`agac inspect -a workflow_name` lists each variant by name (`foo_1`, `foo_2`,
`foo_3`). The `Used by` line of `agac inspect action` shows a versioned consumer
as `foo (×3)`. To see how one variant is configured, inspect that variant:

```bash
agac inspect action -a workflow_name foo_1     # full config and prompt text for variant 1
```

To see the rendered prompts of each iteration, enable prompt debug:

```yaml
- name: extract_variants
  versions:
    range: [1, 3]
  prompt_debug: true
```

## See Also

- [Context Scope](../context/context-scope) - Control the flow of fields
- [Field References](../context/field-references) - Get the version outputs
