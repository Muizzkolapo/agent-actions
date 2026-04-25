# Context Scope Guide

`context_scope` controls what data flows where. Required on every action that reads upstream data.

---

## Three directives

| Directive | LLM sees? | In output? | Use for |
|-----------|:---------:|:----------:|---------|
| `observe` | Yes | No | Data the action needs to process (costs tokens) |
| `passthrough` | No | Yes | Fields downstream needs (zero tokens) |
| `drop` | No | No | Exclude from context (data stays on bus) |

---

## Observe

What the LLM sees. Every `{{ field }}` in your prompt must have its namespace in observe.

```yaml
context_scope:
  observe:
    - source.review_text                    # single field
    - extract_claims.*                       # all fields from namespace
    - seed.rubric                            # seed data
```

### Resolution

```
observe: [flatten_canonical_questions.question_text]

1. Read record content dict
2. Look up key "flatten_canonical_questions"
3. Read field "question_text" from that namespace
4. Inject into LLM context
```

### All references must be namespaced

```yaml
# CORRECT
observe:
  - summarize_page_content.summary        # namespace.field
  - extract_raw_qa.*                       # namespace.wildcard
  - source.page_content                    # source namespace

# WRONG -- rejected at preflight
observe:
  - summary                                # bare field -- which namespace?
  - page_content                           # ambiguous
```

### Wildcard expansion for versions

```yaml
observe: [extract_raw_qa.*]
# Expands to: extract_raw_qa_1.*, extract_raw_qa_2.*, extract_raw_qa_3.*
```

### Long-reach observe

Any action can read any upstream namespace regardless of distance:

```
Step 4:  flatten_canonical_questions.question_text produced
Step 8:  select_approved_questions reads flatten_canonical_questions.question_text
         (4 steps back -- works because additive model preserves all namespaces)
```

---

## Passthrough

Fields routed to output without the LLM seeing them. Zero token cost.

```yaml
context_scope:
  observe:
    - pick_pattern.*
  passthrough:
    - consolidate_answer_from_source.final_source_quote
    - source.review_id
```

The LLM sees `pick_pattern.*`. It does NOT see `final_source_quote`. But `final_source_quote` is included in the action's output record.

---

## Drop

Exclude fields from context. Data stays on the bus — downstream actions can still observe it.

```yaml
context_scope:
  observe:
    - select_approved_questions.*
  drop:
    - select_approved_questions.vote_summary
    - select_approved_questions.filter
```

The LLM sees all `select_approved_questions` fields **except** `vote_summary` and `filter`. Those fields still exist on the record.

Use for bias prevention: `drop: [source.star_rating]` prevents scorers from anchoring on user ratings.

---

## Seed data

Config key is `seed_path:`, reference prefix is `seed.`:

```yaml
defaults:
  context_scope:
    seed_path:
      rubric: $file:evaluation_rubric.json
```

In prompts: `{{ seed.rubric.scoring_criteria }}`. In observe for tool UDFs: `observe: [seed.rubric]`.

**Important:** Runtime namespace is `seed.` NOT `seed_data.`. Using `seed_data.rubric` silently resolves to empty.

---

## Resolution order

1. Resolve `observe` references from record content
2. Apply `drop` exclusions (on a copy -- original record untouched)
3. Apply `passthrough` (merged into output AFTER LLM call)

---

## Error modes

| Scenario | Result |
|----------|--------|
| Namespace exists, field exists | Value injected |
| Namespace exists, field missing | `null` -- no error |
| Namespace is `null` (skipped action) | Empty -- no error |
| **Namespace missing entirely** | **`ObserveResolutionError`** |

---

## Guards

Guard conditions use the same `namespace.field` format:

```yaml
guard:
  condition: 'aggregate_scores.consensus_score >= 6'
  on_false: filter
```

See [guards.md](guards.md) for full reference.

---

## Non-JSON mode

For models that can't produce JSON, use `output_field`:

```yaml
- name: classify_issue
  json_mode: false
  output_field: issue_type
```

Result stored as: `content["classify_issue"]["issue_type"] = "plain text"`

---

## Debugging

```bash
agac render -a workflow    # See resolved observe/passthrough/drop
```

Set `prompt_debug: true` on an action to see the full rendered prompt with resolved context.
