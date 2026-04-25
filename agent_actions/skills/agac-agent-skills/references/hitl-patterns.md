# HITL Patterns

Human-in-the-loop: pause the pipeline for human review.

---

## Basic HITL

```yaml
- name: review_answers
  dependencies: [auto_review_quality]
  kind: hitl
  granularity: File
  intent: "Human reviews consolidated answers for quality"
  context_scope:
    observe:
      - flatten_canonical_questions.question_text
      - consolidate_answer_from_source.final_answer
      - auto_review_quality.*
```

The pipeline pauses. A web UI shows records for human review. Decisions are stored under the action namespace:

```json
{
  "content": {
    "...upstream...": "...",
    "review_answers": {
      "hitl_status": "approved",
      "user_comment": "Looks correct"
    }
  }
}
```

HITL output is **namespaced** under the action name, just like LLM and tool output.

---

## Auto-Review + HITL Triage

Skip HITL when the LLM auto-review passes:

```yaml
- name: auto_review_quality
  dependencies: [consolidate_answer]
  # LLM auto-reviews each answer

- name: review_consolidated_answers
  dependencies: [auto_review_quality]
  kind: hitl
  granularity: File
  guard:
    condition: 'auto_review_quality.content_quality != "pass"'
    on_false: skip  # skip HITL if auto-review passed
```

When skipped: `content["review_consolidated_answers"] = null`. Downstream handles the null namespace.

---

## HITL with Guard Pre-Filter

Only show high-priority records to the human:

```yaml
- name: review_critical
  kind: hitl
  guard:
    condition: 'assess_severity.severity == "critical"'
    on_false: filter  # non-critical records skip human review entirely
```

---

## Common mistakes

1. **Not using passthrough for context fields** — HITL UI needs to display upstream data. Use `observe` for fields the reviewer needs to see.

2. **Guard filtering all records** — If the guard condition is too strict, HITL gets zero records. Check scores/conditions with `record_limit: 2` first.

3. **Expecting flat HITL output** — HITL decisions are namespaced under the action name, not flat-merged into content. Access via `content["review_action"]["hitl_status"]`.
