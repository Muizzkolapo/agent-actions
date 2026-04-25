# Guards

Conditional execution gates. Evaluate a condition before running the action.

---

## Config

```yaml
- name: generate_response
  guard:
    condition: 'aggregate_scores.consensus_score >= 6'
    on_false: filter
```

## Guard references MUST be namespaced

Guard conditions use `namespace.field` format — same as observe. Bare field names are rejected at preflight.

```yaml
# CORRECT
guard:
  condition: 'aggregate_scores.consensus_score >= 6'

# CORRECT
guard:
  condition: 'aggregate_votes.filter == "keep"'

# WRONG -- bare field, rejected at preflight
guard:
  condition: 'consensus_score >= 6'

# WRONG -- ambiguous
guard:
  condition: 'filter == "keep"'
```

**Why:** With the additive model, `content` has many namespaces. A bare field name could exist in multiple namespaces. Namespace prefix eliminates ambiguity.

---

## Behaviors

| `on_false` | Record | Namespace | Downstream |
|-----------|--------|-----------|------------|
| **`filter`** | Record **removed** | No namespace created | No downstream processing |
| **`skip`** | Record **survives** | `action_name: null` | Downstream runs, must handle null |

---

## `filter` -- record removed

The record is gone. No downstream action sees it.

```yaml
guard:
  condition: 'aggregate_votes.filter == "keep"'
  on_false: filter
```

Use for quality gates where failing records should not proceed.

## `skip` -- action skipped, record survives

The action doesn't run, but the record passes through with a null namespace. All upstream namespaces preserved.

```yaml
guard:
  condition: 'auto_review_quality.content_quality != "pass"'
  on_false: skip
```

After skip:
```json
{
  "content": {
    "...all upstream namespaces...": "...",
    "review_consolidated_answers": null
  }
}
```

Downstream actions observing `review_consolidated_answers.*` get empty data.

---

## Supported operators

| Operator | Example |
|----------|---------|
| `==`, `!=` | `field == "value"` |
| `>=`, `<=`, `>`, `<` | `field >= 6` |
| `or`, `and` | `cond_a or cond_b` |
| `in` | `field in ["a", "b"]` |
| `true`, `false` | `field == true` |

---

## Guard and the additive model

- `filter`: Record removed — no namespace impact (record is gone)
- `skip`: Null namespace added — all upstream namespaces preserved
- Guards never destroy upstream namespaces

## Guard-skip tombstones

Guard-skipped records (`on_false: skip`) have `_unprocessed: True` but are valid pipeline data. They do NOT cascade as upstream failures — downstream actions should still process them.
