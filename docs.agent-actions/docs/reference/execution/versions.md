---
title: Version Actions
sidebar_position: 7
---

# Version Actions

What happens when you need to run the same action multiple times with different parameters? Loop actions enable you to generate multiple agent instances from a single configuration, creating parallel processing pipelines for operations like multi-strategy extraction or iterative refinement.

Think of version actions like running multiple experiments simultaneously - same methodology, different parameters.

## Overview

Loop actions solve the problem of repeating similar operations without duplicating configuration. Instead of defining `extract_raw_qa_1`, `extract_raw_qa_2`, `extract_raw_qa_3` separately, you define one action with a loop configuration.

```yaml
actions:
  - name: extract_raw_qa
    versions:
      range: [1, 3]  # Creates extract_raw_qa_1, extract_raw_qa_2, extract_raw_qa_3
    prompt: |
      Extract questions using strategy {{ i }}
```

## Version Configuration

### Basic Syntax

```yaml
actions:
  - name: base_action_name
    versions:
      param: i              # Loop variable name (default: i)
      range: [start, end]   # Inclusive range
      mode: parallel        # Execution mode (default: parallel)
```

### Version Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `param` | string | `i` | Variable name for loop counter |
| `range` | array | Required | `[start, end]` - inclusive range |
| `mode` | string | `parallel` | Execution mode: `parallel` or `sequential` |

### Expanded Agent Names

Loop actions expand to numbered agents:

```yaml
# Source configuration
- name: extract_raw_qa
  versions:
    range: [1, 3]

# Expands to:
# - extract_raw_qa_1 (i=1)
# - extract_raw_qa_2 (i=2)
# - extract_raw_qa_3 (i=3)
```

## Template Variables

Inside version actions, you have access to loop variables in prompts and configurations:

| Variable | Type | Description |
|----------|------|-------------|
| `{{ i }}` | int | Current version iteration value |
| `{{ idx }}` | int | Zero-based index (0, 1, 2...) |
| `{{ loop.length }}` | int | Total number of iterations |
| `{{ loop.first }}` | bool | True on first iteration |
| `{{ loop.last }}` | bool | True on last iteration |

### Example with Template Variables

```yaml
- name: multi_strategy_extract
  versions:
    range: [1, 5]
  prompt: |
    You are using extraction strategy {{ i }} of {{ loop.length }}.

    {% if loop.first %}
    This is the first strategy - be conservative.
    {% elif loop.last %}
    This is the final strategy - be comprehensive.
    {% else %}
    This is strategy {{ i }} - balance precision and recall.
    {% endif %}

    Extract facts from: {{ source.content }}
```

## Version Consumption

What happens when downstream actions need to consume outputs from all version iterations? Loop consumption merges outputs from version iterations and makes them available to downstream actions.

### Configuration

```yaml
actions:
  - name: extract_raw_qa
    versions:
      range: [1, 3]
    # Each iteration produces: {"questions": [...]}

  - name: flatten_questions
    dependencies: [extract_raw_qa]  # References loop base name
    version_consumption:
      source: extract_raw_qa        # Loop to consume
      pattern: merge                # Merge pattern
    context_scope:
      observe:
        - extract_raw_qa.*          # Wildcard reference
```

### How Version Consumption Works

1. **Loop Expansion**: `extract_raw_qa` expands to `extract_raw_qa_1`, `extract_raw_qa_2`, `extract_raw_qa_3`

2. **Output Generation**: Each iteration produces output
   ```json
   // extract_raw_qa_1 output
   {"questions": ["Q1a", "Q1b"]}

   // extract_raw_qa_2 output
   {"questions": ["Q2a", "Q2b"]}

   // extract_raw_qa_3 output
   {"questions": ["Q3a", "Q3b"]}
   ```

3. **Field Prefixing**: Outputs are merged with agent name prefixes to avoid collisions
   ```json
   // Merged output for flatten_questions
   {
     "extract_raw_qa_1_questions": ["Q1a", "Q1b"],
     "extract_raw_qa_2_questions": ["Q2a", "Q2b"],
     "extract_raw_qa_3_questions": ["Q3a", "Q3b"]
   }
   ```

4. **Field Access**: In prompts, access prefixed fields
   ```yaml
   - name: flatten_questions
     prompt: |
       Strategy 1 questions: {{ extract_raw_qa_1_questions }}
       Strategy 2 questions: {{ extract_raw_qa_2_questions }}
       Strategy 3 questions: {{ extract_raw_qa_3_questions }}

       Combine and deduplicate these questions.
   ```

### Field Prefix Patterns

When using `context_scope` with version consumption, use field prefix patterns for wildcard matching:

```yaml
context_scope:
  observe:
    - extract_raw_qa.*  # In config: wildcard reference
    # After expansion: extract_raw_qa_  (field prefix pattern)
    # Matches: extract_raw_qa_1_questions, extract_raw_qa_2_questions, etc.
```

The system automatically converts wildcard version references (`extract_raw_qa.*`) to field prefix patterns (`extract_raw_qa_`) during workflow initialization. This ensures that all prefixed fields from version iterations are accessible.

## Execution Modes

### Parallel Mode (Default)

Loop iterations execute concurrently:

```yaml
- name: parallel_extract
  versions:
    range: [1, 5]
    mode: parallel  # Default
  # All 5 iterations run simultaneously
```

**Use when:**
- Iterations are independent
- Want fastest execution time
- Have sufficient API quota/concurrency

### Sequential Mode

Loop iterations execute one at a time:

```yaml
- name: sequential_refine
  versions:
    range: [1, 3]
    mode: sequential
    dependencies: [initial_draft]
  # Iterations run: refine_1 → refine_2 → refine_3
```

**Use when:**
- Later iterations depend on earlier ones
- Need to control API rate limits
- Processing order matters

## Common Patterns

### Multi-Strategy Extraction

Extract data using multiple strategies, then merge results:

```yaml
- name: extract_with_strategies
  versions:
    range: [1, 3]
  prompt: |
    Use extraction strategy {{ i }}:
    {% if i == 1 %}
    - Focus on explicit statements
    {% elif i == 2 %}
    - Focus on implicit meanings
    {% else %}
    - Focus on contextual clues
    {% endif %}

    Extract from: {{ source.text }}

- name: combine_extractions
  dependencies: [extract_with_strategies]
  version_consumption:
    source: extract_with_strategies
    pattern: merge
  prompt: |
    You have {{ loop.length }} extraction strategies:
    {% for strategy in [1, 2, 3] %}
    Strategy {{ strategy }}: {{ extract_with_strategies_{{strategy}}_results }}
    {% endfor %}

    Combine and deduplicate these extractions.
```

### Iterative Refinement

Refine output across multiple iterations:

```yaml
- name: draft_content
  # Initial draft

- name: refine_iteration
  versions:
    range: [1, 3]
    mode: sequential
  dependencies:
    - "{% if i == 1 %}draft_content{% else %}refine_iteration_{{ i-1 }}{% endif %}"
  prompt: |
    This is refinement iteration {{ i }} of {{ loop.length }}.
    Improve: {{ content }}
```

### Parallel Model Comparison

Compare outputs from different models:

```yaml
- name: model_comparison
  versions:
    range: [1, 3]
  model_vendor: |
    {% if i == 1 %}openai
    {% elif i == 2 %}anthropic
    {% else %}google
    {% endif %}
  prompt: "Analyze: {{ source.text }}"

- name: choose_best_output
  dependencies: [model_comparison]
  version_consumption:
    source: model_comparison
    pattern: merge
  prompt: |
    Compare these analyses:
    Model 1 (OpenAI): {{ model_comparison_1_analysis }}
    Model 2 (Anthropic): {{ model_comparison_2_analysis }}
    Model 3 (Google): {{ model_comparison_3_analysis }}

    Select the best analysis.
```

### Batch Processing with Different Parameters

Process data with varying parameters:

```yaml
- name: process_with_temps
  versions:
    param: temp
    range: [1, 5]
  temperature: "{{ 0.2 * temp }}"  # 0.2, 0.4, 0.6, 0.8, 1.0
  prompt: "Process with temperature {{ 0.2 * temp }}: {{ source.text }}"
```

## Dependencies with Loops

### Version Depending on Regular Action

```yaml
- name: preprocess
  # Regular action

- name: extract_variants
  versions:
    range: [1, 3]
  dependencies: [preprocess]  # All version iterations depend on preprocess
```

### Regular Action Depending on Version

```yaml
- name: extract_variants
  versions:
    range: [1, 3]

- name: combine_results
  dependencies: [extract_variants]  # Reference loop base name
  version_consumption:
    source: extract_variants
    pattern: merge
```

### Version Depending on Another Version

```yaml
- name: first_pass
  versions:
    range: [1, 2]

- name: second_pass
  versions:
    range: [1, 3]
  dependencies: [first_pass]  # All second_pass iterations wait for all first_pass
  version_consumption:
    source: first_pass
    pattern: merge
```

## Context Scope with Loops

### Auto-Expansion

When you reference a loop base name in `context_scope`, the system automatically expands it:

```yaml
- name: extract_variants
  versions:
    range: [1, 3]
  # Produces: extract_variants_1, extract_variants_2, extract_variants_3

- name: analyze
  dependencies: [extract_variants]
  context_scope:
    observe:
      - extract_variants.*  # Wildcard reference to loop base name

# After expansion:
# dependencies: [extract_variants_1, extract_variants_2, extract_variants_3]
# context_scope:
#   observe:
#     - extract_variants_  # Field prefix pattern (matches all prefixed fields)
```

### Specific Version Iteration

Reference a specific iteration:

```yaml
context_scope:
  observe:
    - extract_variants_1.specific_field  # Only from iteration 1
    - extract_variants_2.specific_field  # Only from iteration 2
```

### Mixed Version and Regular Dependencies

```yaml
- name: extract_variants
  versions:
    range: [1, 3]

- name: classify_type
  # Regular action

- name: combine
  dependencies: [extract_variants, classify_type]
  context_scope:
    observe:
      - extract_variants.*     # Field prefix pattern for loop
      - classify_type.category # Regular field reference
```

## Best Practices

### 1. Use Descriptive Base Names

```yaml
# Good
- name: multi_strategy_extraction
  versions:
    range: [1, 3]

# Avoid
- name: extract
  versions:
    range: [1, 3]
```

### 2. Document Strategy Differences

```yaml
- name: extract_with_strategies
  versions:
    range: [1, 3]
  intent: |
    Multi-strategy extraction:
    1. Conservative (high precision)
    2. Balanced (precision-recall)
    3. Comprehensive (high recall)
  prompt: |
    {% if i == 1 %}
    Strategy 1: Conservative approach...
    {% elif i == 2 %}
    Strategy 2: Balanced approach...
    {% else %}
    Strategy 3: Comprehensive approach...
    {% endif %}
```

### 3. Choose Appropriate Execution Mode

```yaml
# Parallel for independent operations
- name: parallel_extract
  versions:
    mode: parallel
    range: [1, 5]

# Sequential for dependent operations
- name: iterative_refine
  versions:
    mode: sequential
    range: [1, 3]
```

### 4. Use Version Consumption for Merging

```yaml
# Always specify loop_consumption when consuming version outputs
- name: combine_strategies
  dependencies: [multi_strategy_extract]
  version_consumption:
    source: multi_strategy_extract
    pattern: merge
  context_scope:
    observe:
      - multi_strategy_extract.*  # Will expand to field prefix pattern
```

### 5. Handle Variable Version Outputs

```yaml
- name: process_merged
  dependencies: [extract_variants]
  version_consumption:
    source: extract_variants
    pattern: merge
  prompt: |
    Process all strategy outputs:
    {% for i in range(1, version_numbers + 1) %}
    Strategy {{ i }}: {{ extract_variants_{{i}}_output | default([]) }}
    {% endfor %}
```

## Error Handling

### Missing Version Configuration

```
ConfigurationError: Loop configuration missing 'range'
  Action: extract_variants

  Fix: Add range to loop configuration:
    versions:
      range: [1, 3]
```

### Invalid Range

```
ConfigurationError: Loop range must be [start, end] with start <= end
  Action: extract_variants
  Range: [3, 1]

  Fix: Ensure start <= end in range
```

### Circular Version Dependencies

```
WorkflowError: Circular dependency detected in loop expansion
  Path: refine_1 -> refine_2 -> refine_1

  Fix: Use sequential mode or remove circular references
```

### Version Consumption Without Declaration

```
ConfigurationError: Dependency 'extract_raw_qa_1' declared but not referenced in context_scope
  Action: flatten_questions

  Fix: Add field prefix pattern to context_scope:
    context_scope:
      observe:
        - extract_raw_qa.*
```

## Performance Considerations

### API Rate Limits

Parallel loops can hit API rate limits:

```yaml
# If hitting rate limits, reduce parallelism
- name: parallel_extract
  versions:
    mode: sequential  # Process one at a time
    range: [1, 10]
```

### Token Usage

Loop consumption increases token usage (all outputs in context):

```yaml
# Be selective about what to observe
context_scope:
  observe:
    - extract_variants_1_summary  # Specific fields only
    - extract_variants_2_summary
    - extract_variants_3_summary
  # Instead of: extract_variants.* (all fields)
```

### Execution Time

Consider trade-offs between parallel and sequential:

```yaml
# Parallel: Faster but more API concurrent requests
versions:
  mode: parallel
  range: [1, 10]  # 10 concurrent API calls

# Sequential: Slower but controlled rate
versions:
  mode: sequential
  range: [1, 10]  # 10 sequential API calls
```

## Debugging Versions

### Inspect Expanded Actions

Use the inspect command to see expanded version actions:

```bash
agac inspect -a workflow_name
```

Output shows expanded actions:
```
Actions (5):
  1. preprocess
  2. extract_variants_1 (version iteration 1)
  3. extract_variants_2 (version iteration 2)
  4. extract_variants_3 (version iteration 3)
  5. combine_results
```

### Enable Prompt Debug

See what data each version iteration receives:

```yaml
- name: extract_variants
  versions:
    range: [1, 3]
  prompt_debug: true  # Print rendered prompts
```

### Check Version Correlation

Verify merged outputs:

```bash
# Check merged outputs in target directory
ls agent_io/target/combine_results/
# Should contain correlated_data.json with merged version outputs
```

## See Also

- [Context Scope](../context/context-scope) - Field flow control
- [Field References](../context/field-references) - Accessing version outputs
- [Workflow Dependencies](./workflow-dependencies) - Dependency patterns
- [Templates](../configuration/templates) - Jinja2 loop templates
