---
title: Context Handling
sidebar_position: 3
---

# Context Handling

How does your data reach the LLM prompt? Agent Actions builds prompt context differently depending on the execution mode - and understanding this difference is essential for writing prompts that work correctly.

Think of context like a letter's envelope and contents. The execution mode determines how the data is "addressed" - batch mode puts fields at the root level, while online mode wraps them under `source`.

## Execution Modes Overview

| Mode | Description | Context Structure |
|------|-------------|-------------------|
| **Online** | Real-time, synchronous execution | Input data available as `source` |
| **Batch** | Asynchronous batch API processing | Input data available at root level |

## Online Mode Context

Let's walk through online mode first. The entire input file is loaded and made available under the `source` namespace:

```yaml
# Workflow config
run_mode: online
```

**Context structure:**
```json
{
  "source": {
    "page_content": "Document text...",
    "url": "https://example.com",
    "metadata": { "author": "John" }
  },
  "seed": {
    "exam_syllabus": { ... }
  }
}
```

**Prompt template:**
```jinja2
Analyze this content: {{ source.page_content }}
From URL: {{ source.url }}
```

### How Online Context is Built

1. Input file is loaded from `staging/` (tracked via `source/` metadata)
2. Parsed content is wrapped under `source` key
3. Seed data is added under `seed` key
4. Previous action outputs are added by action name
5. `context_scope.observe` fields are merged in

## Batch Mode Context

Here's where it differs: in batch mode, each row of data is processed independently. The row data is available directly at the root level, **not** under a `source` namespace:

```yaml
# Workflow config
run_mode: batch
```

**Context structure:**
```json
{
  "page_content": "Document text...",
  "url": "https://example.com",
  "metadata": { "author": "John" },
  "seed": {
    "exam_syllabus": { ... }
  }
}
```

**Prompt template:**
```jinja2
Analyze this content: {{ page_content }}
From URL: {{ url }}
```

### How Batch Context is Built

1. Input data is split into individual rows/records
2. Each row's fields are available directly at root level
3. Seed data is added under `seed` key
4. `context_scope.observe` fields are merged in
5. Preflight validation runs against first row before submission

## Writing Mode-Agnostic Prompts

To write prompts that work in both modes, use conditional logic:

```jinja2
{% if source is defined %}
  {# Online mode - data under source #}
  Content: {{ source.page_content }}
{% else %}
  {# Batch mode - data at root #}
  Content: {{ page_content }}
{% endif %}
```

Or use a helper macro:

```jinja2
{% macro get_field(field_name) %}
  {% if source is defined %}{{ source[field_name] }}{% else %}{{ field_name }}{% endif %}
{% endmacro %}

Content: {{ get_field('page_content') }}
```

## Common Context Variables

| Variable | Description | Available In |
|----------|-------------|--------------|
| `source` | Input record (wrapped) | Online only |
| `seed` | Static seed data | Both modes |
| `{action_name}` | Previous action output | Both modes |
| Root fields | Input record fields (unwrapped) | Batch only |

## Preflight Validation

You might wonder: how do I catch context errors before making API calls? Both modes run preflight validation **per action** before that action's LLM call.

### PreFlightValidator Scope

Preflight runs **per action** (not whole workflow) and validates 3 things:

| Check | What it does |
|-------|--------------|
| **Template variables** | Tries to render Jinja2 template against context, catches undefined variables |
| **Context structure** | Checks if expected fields exist in context |
| **Agent config** | Checks `model_vendor` exists for LLM actions |

### Context Sources by Action Position

The available context depends on where the action is in the workflow:

| Action Position | Context Sources |
|-----------------|-----------------|
| **Action 0** (first, no parent) | `source` (staging data) + `seed` (seed data) |
| **Action N** (has dependencies) | `source` + `seed` + previous action outputs (`{action_name}.field`) |

**Example for action 0:**
```json
{
  "source": { /* from staging/*.json */ },
  "seed": { /* from seed_data/*.json */ }
}
```

**Example for action 2 (depends on action 0, action 1):**
```json
{
  "source": { /* original staging data */ },
  "seed": { /* seed data */ },
  "action_0": { /* output fields from action 0 */ },
  "action_1": { /* output fields from action 1 */ }
}
```

### Online Preflight
- Validates template against actual `source` structure
- Catches missing fields in `source.field` references
- Error example: `missing_references=['referenced_in']`

### Batch Preflight
- Validates template against first data row + seed data
- Does NOT include `source` wrapper during validation
- Error example: `missing_references=['source']`

This difference explains why the same template can produce different errors in each mode:

| Mode | Template | Result |
|------|----------|--------|
| Online | `{{ source.field }}` | Works (source exists) |
| Batch | `{{ source.field }}` | Fails (`source` undefined) |
| Online | `{{ field }}` | Fails (field at root undefined) |
| Batch | `{{ field }}` | Works (fields at root) |

:::warning
This is a common source of confusion. If you switch from online to batch mode, your templates may break - and vice versa.
:::

## Context Scope Features

Both modes support `context_scope` for controlling what data is available:

```yaml
actions:
  - name: my_action
    context_scope:
      observe:
        - seed.exam_syllabus    # Add seed data to context
        - prev_action.result    # Add previous action output
      drop:
        - source.sensitive_field  # Remove field from context
```

### observe

Merges additional data into the LLM context:
- **Online**: Merged into context alongside `source`
- **Batch**: Merged into context alongside root fields

### drop

Removes fields from the context before sending to LLM:
- **Online**: Uses `DataTransformer.remove_schema_objects()`
- **Batch**: Uses direct `dict.pop()`

Both produce equivalent results - the difference is implementation only.

## Best Practices

### 1. Choose One Mode Per Agentic Workflow

Don't switch modes mid-workflow. Design for one mode:

```yaml
# Good - consistent mode
defaults:
  run_mode: batch

actions:
  - name: action_1
  - name: action_2
```

### 2. Match Template to Mode

If using batch mode, don't use `source.*` references:

```jinja2
{# Batch mode template #}
{{ page_content }}     {# Correct #}
{{ source.page_content }}  {# Wrong - source undefined #}
```

### 3. Use Seed Data for Static Content

Seed data works identically in both modes:

```jinja2
{# Works in both modes #}
Syllabus: {{ seed.exam_syllabus.topics }}
```

### 4. Test in Target Mode

Always test prompts in the mode you'll use for production:

```bash
# Test in batch mode
agac run -a my_workflow --validate-only

# Test in online mode (default)
agac run -a my_workflow --run-mode online --validate-only
```

## Debugging Context Issues

When context errors occur, Agent Actions provides helpful diagnostics. Let's explore how to use them:

### Check Available References

Error messages show available references:

```
available_references=['page_content', 'url', 'seed', 'seed.exam_syllabus']
missing_references=['source']
```

This tells you:
- `source` is NOT available (batch mode)
- `page_content`, `url` ARE available at root

### Enable Debug Logging

```bash
agac run -a my_workflow --log-level DEBUG
```

Look for:
```
Built LLM context for batch mode with 5 keys
```
vs
```
Built LLM context for realtime mode with 1 keys
```
