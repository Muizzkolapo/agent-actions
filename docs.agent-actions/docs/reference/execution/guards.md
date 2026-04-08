---
title: Guards
sidebar_position: 1
---

# Guards

Guards evaluate conditions and decide whether an action should run for each record, acting as quality checkpoints in your workflow.

## Syntax

```yaml
- name: my_action
  guard:
    condition: "expression"
    on_false: "skip" | "filter"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `condition` | string | Required | Expression evaluated against upstream data |
| `on_false` | string | `filter` | Action when condition is false |
| `passthrough_on_error` | boolean | `true` | Pass record through if evaluation fails |

## on_false Options

| Value | Description |
|----------|-------------|
| `skip` | Action skipped, record continues to downstream actions |
| `filter` | Record removed from workflow entirely |

## Condition Expressions

### Comparison Operators

```yaml
guard:
  condition: "score > 85"
  condition: "status == 'approved'"
  condition: "facts != []"
```

| Operator | Description |
|----------|-------------|
| `==`, `!=` | Equality |
| `>`, `>=`, `<`, `<=` | Comparison |
| `and`, `or`, `not` | Logical |

### Advanced Operators

| Operator | Example |
|----------|---------|
| `IN` | `status IN ["active", "pending"]` |
| `NOT IN` | `category NOT IN ["spam"]` |
| `CONTAINS` | `tags CONTAINS "important"` |
| `LIKE` | `name LIKE "prod_*"` |
| `BETWEEN` | `score BETWEEN 50 AND 100` |
| `IS NULL` | `description IS NULL` |

### Boolean Values

Boolean keywords are case-insensitive, matching SQL convention:

```yaml
guard:
  condition: 'passes_filter == true'   # valid
  condition: 'passes_filter == True'   # valid
  condition: 'passes_filter == TRUE'   # valid
```

Prefer explicit comparison over a bare field reference for boolean fields. A bare reference evaluates using Python truthiness — this fails silently when the upstream action stores `"false"` as a string (which is truthy) rather than a Python `bool`:

```yaml
# Fragile — string "false" is truthy, so the guard never filters
condition: 'passes_filter'

# Explicit — correct regardless of whether the value is a bool or a string
condition: 'passes_filter == true'
```

### Built-in Functions

```yaml
guard:
  condition: 'len(items) > 0'
  condition: 'max(scores) >= 85'
```

Supported: `len()`, `str()`, `int()`, `float()`, `abs()`, `min()`, `max()`

## Examples

### Filter Empty Results

```yaml
- name: canonicalize_facts
  dependencies: fact_extractor
  guard:
    condition: 'candidate_facts_list != []'
    on_false: "filter"
```

### Skip Optional Processing

```yaml
- name: enhance_summary
  guard:
    condition: 'needs_enhancement == true'
    on_false: "skip"
```

### Quality Gate

```yaml
- name: generate_final_output
  guard:
    condition: 'quality_score >= 85'
    on_false: "filter"
```

## Context Access

Guards can access:

| Source | Syntax |
|--------|--------|
| Direct field | `candidate_facts_list` |
| Specific action | `extract_facts.count` |
| Context scope observed | `num_similar_facts` |

```yaml
- name: validate
  context_scope:
    observe:
      - group_by_similarity.num_similar_facts
  guard:
    condition: 'num_similar_facts != 1'
    on_false: "skip"
```

## Downstream Behavior

How guard results affect downstream actions in a multi-action workflow:

| on_false | Output record | Downstream actions |
|----------|--------------|-------------------|
| `skip` | Original content preserved, `metadata.reason: "guard_skip"` | **Process normally** — each action evaluates its own guard independently |
| `filter` | Record excluded from output | **Never sees it** — record is removed from the pipeline |

### Skipped records flow downstream

When Action A skips a record (`on_false: skip`), Action B still receives it and can process it with its own LLM call. Each action's guard is independent:

```yaml
actions:
  - name: extract_facts
    guard:
      condition: 'status == "active"'
      on_false: "skip"       # Inactive records pass through with original content

  - name: generate_summary
    dependencies: extract_facts
    # Receives ALL records from extract_facts, including skipped ones
    # Can define its own guard or process everything
```

### Upstream failures are short-circuited

When an upstream action fails for some records (e.g., batch API errors), those records are marked with `_unprocessed: true` and automatically skipped by all downstream actions — no context loading, prompt rendering, or LLM calls are wasted. These records are preserved in the output for lineage traceability.

## Error Handling

Guard evaluation errors are classified into three categories, each with different handling:

| Category | Example | `passthrough_on_error` respected? | Behavior |
|----------|---------|-----------------------------------|----------|
| **Semantic** | Unquoted string (`status == approved`) | No — always uses `on_false` | Condition itself is broken; cached after first occurrence |
| **Data** | Missing field, type mismatch | Yes | Field absent for this specific record |
| **Timeout** | Evaluation exceeded time limit | Yes | Transient failure |

**Semantic errors** bypass `passthrough_on_error` because the condition is fundamentally broken — passing records through would give wrong results for every record, not just one. These errors are logged once (circuit breaker), not per-record.

**Data and timeout errors** respect `passthrough_on_error` (default: `true`). Set to `false` to apply the configured `on_false` behavior instead:

```yaml
guard:
  condition: 'passes_filter == true'
  on_false: filter
  passthrough_on_error: false   # filter the record if evaluation fails
```

:::tip
When a guard silently lets records through unexpectedly, check `target/errors.json` for `G002` events — these indicate evaluation failures that were swallowed by `passthrough_on_error: true`.
:::

## Common Mistakes

### Unquoted String Literals

String values on the right-hand side of comparisons **must be quoted**. Unquoted strings are treated as field references and produce a preflight validation error:

```yaml
# WRONG — "approved" is interpreted as a field name
guard:
  condition: 'hitl_status == approved'

# CORRECT — quote string literals
guard:
  condition: 'hitl_status == "approved"'
```

## Limitations

- **No external calls** - Guards can't make API requests
- **Limited functions** - Only built-in functions available
- **Not supported with File granularity** - Guards evaluate per-record
- **Single expression** - Complex logic should use tool actions

:::warning
Guards are not supported with File granularity. Implement filtering logic within your tool function instead.
:::

## See Also

- [Context Scope](../context/context-scope) - Field visibility
- [Granularity](./granularity) - Record vs file processing
