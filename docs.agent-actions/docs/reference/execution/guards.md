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
    clause: "expression"
    behavior: "skip" | "filter"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `clause` | string | Required | Expression evaluated against upstream data |
| `behavior` | string | `filter` | Action when clause is false |
| `passthrough_on_error` | boolean | `true` | Pass record through if evaluation fails |

## Behavior Options

| Behavior | Description |
|----------|-------------|
| `skip` | Action skipped, record continues to downstream actions |
| `filter` | Record removed from workflow entirely |

## Condition Expressions

### Comparison Operators

```yaml
guard:
  clause: "score > 85"
  clause: "status == 'approved'"
  clause: "facts != []"
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

### Built-in Functions

```yaml
guard:
  clause: 'len(items) > 0'
  clause: 'max(scores) >= 85'
```

Supported: `len()`, `str()`, `int()`, `float()`, `abs()`, `min()`, `max()`

## Examples

### Filter Empty Results

```yaml
- name: canonicalize_facts
  dependencies: fact_extractor
  guard:
    clause: 'candidate_facts_list != []'
    behavior: "filter"
```

### Skip Optional Processing

```yaml
- name: enhance_summary
  guard:
    clause: 'needs_enhancement == true'
    behavior: "skip"
```

### Quality Gate

```yaml
- name: generate_final_output
  guard:
    clause: 'quality_score >= 85'
    behavior: "filter"
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
    clause: 'num_similar_facts != 1'
    behavior: "skip"
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
