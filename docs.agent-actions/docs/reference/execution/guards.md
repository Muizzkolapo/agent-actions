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
| `on_false` | string | `filter` (SQL) / `skip` (UDF) | Action when condition is false. **Default depends on guard type**: SQL-style guards default to `filter`; UDF guards default to `skip`. |
| `passthrough_on_error` | boolean | `true` | Pass record through if evaluation fails |

## on_false Options

| Value | Description |
|----------|-------------|
| `skip` | Action skipped, record continues to downstream actions with original content preserved |
| `filter` | Record excluded from action output entirely — downstream actions never see it |
| `warn` | Record proceeds to LLM processing normally; a warning is logged |

## Condition Expressions

### Comparison Operators

```yaml
guard:
  condition: "upstream_action.score > 85"
  condition: "upstream_action.status == 'approved'"
  condition: "upstream_action.facts != []"
```

| Operator | Description |
|----------|-------------|
| `==`, `!=` | Equality |
| `>`, `>=`, `<`, `<=` | Comparison |
| `and`, `or`, `not` | Logical |

`not` binds looser than every comparison operator and tighter than `and`/`or`: `not x == 1`
negates the comparison, reading as `not (x == 1)`, and `not x == 1 and y == 2` reads as
`(not (x == 1)) and (y == 2)`. Written on a field alone, `not x`, it negates the field's
truthiness instead.

### Advanced Operators

| Operator | Example |
|----------|---------|
| `IN` | `triage.status IN ["active", "pending"]` |
| `NOT IN` | `classify.category NOT IN ["spam"]` |
| `CONTAINS` | `extract.tags CONTAINS "important"` |
| `LIKE` | `lookup.name LIKE "prod%"` |
| `BETWEEN` | `score_review.score BETWEEN 50 AND 100` |
| `NOT BETWEEN` | `score_review.score NOT BETWEEN 50 AND 100` |
| `IS NULL` | `summarize.description IS NULL` |

Each field carries its action prefix, as every guard field must — see
[Context Access](#context-access).

`BETWEEN` includes both ends of its range, so the example keeps a score of 50 and a score of
100. The range can also be written as a list, `score_review.score BETWEEN [50, 100]`, and the
two forms mean the same. The ends are two numbers or two quoted strings, written in the
clause. A clause that gives one end only (`BETWEEN 50`), gives `NULL` or a boolean for an end,
or names a field for an end (`BETWEEN limits.low AND limits.high`), is refused before the
run starts. To keep what is outside a range, write `NOT BETWEEN`, or put the range in
parentheses: `NOT (score_review.score BETWEEN 50 AND 100)`.

`LIKE` and `NOT LIKE` take SQL wildcards, not a glob: `%` is any run of characters and `_` is
exactly one character. Everything else, `*` included, is literal. The pattern must match the whole
value, case is ignored, and there is no escape for a literal `%` or `_`. The example keeps
`prod_east` and `PROD_WEST`; `"prod_*"` would keep only a six-character name ending in a literal `*`.

### Functions

| Function | Example |
|----------|---------|
| `LENGTH` | `LENGTH(extract.items) > 2` |
| `UPPER` | `UPPER(classify.category) == "SPAM"` |
| `LOWER` | `LOWER(classify.category) == "spam"` |
| `TRIM` | `TRIM(summarize.title) != ""` |

Each takes exactly one argument — a field, string, number, boolean, or `NULL` — and returns a
plain value a comparison can use. A function call is not itself a valid argument, so these do
not nest: `LENGTH(TRIM(x))` is refused. `LENGTH` counts a string's characters or a list's items,
or treats a non-string, non-list value as its string form; `NULL` counts as length `0`. A field
used inside a function still needs its action prefix, exactly as it would outside one.

Guard functions are not available in an `expression` [expectation](../validation/expectations.md#expressions)
condition, which shares this grammar but evaluates against an action's own output, not a
stored record.

`IS NULL` is the one to watch. A name it cannot resolve — misspelled, or written without its
prefix — is treated as null, so the clause is true and the record passes. Every other operator
reports a missing field and filters; `IS NULL` alone lets it through, and logs nothing while
doing it. A guard written `summarize.descriptio IS NULL` filters nothing and says nothing.

### Boolean Values

Boolean keywords are case-insensitive, matching SQL convention:

```yaml
guard:
  condition: 'upstream_action.passes_filter == true'   # valid
  condition: 'upstream_action.passes_filter == True'   # valid
  condition: 'upstream_action.passes_filter == TRUE'   # valid
```

Prefer explicit comparison over a bare field reference for boolean fields. A bare reference evaluates using Python truthiness — this fails silently when the upstream action stores `"false"` as a string (which is truthy) rather than a Python `bool`:

```yaml
# Fragile — string "false" is truthy, so the guard never filters
condition: 'upstream_action.passes_filter'

# Explicit — correct regardless of whether the value is a bool or a string
condition: 'upstream_action.passes_filter == true'
```

### Built-in Functions

```yaml
guard:
  condition: 'len(upstream_action.items) > 0'
  condition: 'max(upstream_action.scores) >= 85'
```

Supported: `len()`, `str()`, `int()`, `float()`, `abs()`, `min()`, `max()`

## Examples

### Filter Empty Results

```yaml
- name: canonicalize_facts
  dependencies: [fact_extractor]
  guard:
    condition: 'fact_extractor.candidate_facts_list != []'
    on_false: "filter"
```

### Skip Optional Processing

```yaml
- name: enhance_summary
  dependencies: [analyze_content]
  guard:
    condition: 'analyze_content.needs_enhancement == true'
    on_false: "skip"
```

### Quality Gate

```yaml
- name: generate_final_output
  dependencies: [evaluate_quality]
  guard:
    condition: 'evaluate_quality.quality_score >= 85'
    on_false: "filter"
```

## Context Access

A guard gates the action before it receives anything, so it reads the record **as stored** —
every namespace the record carries, addressed as `action_name.field`. A record carries the
actions upstream of it through `dependencies`, so a clause names only those: preflight refuses
a guard that names an action running beside or after its own, one on a parallel branch, or its own
action: the guard runs before the action, so the action's output is not yet on the record.

| Source | Syntax |
|--------|--------|
| Upstream action field | `extract_facts.count` |
| A dependency's field, whether or not the action observes it | `group_by_similarity.num_similar_facts` |

`context_scope` describes what the action is handed once the guard has let the record through.
It does not decide the verdict: a field the action `drop`s still answers a clause, and the
guard field does not have to appear in `observe`.

```yaml
- name: validate
  dependencies: [group_by_similarity]
  context_scope:
    observe:
      - group_by_similarity.num_similar_facts
  guard:
    condition: 'group_by_similarity.num_similar_facts != 1'
    on_false: "skip"
```

## Downstream Behavior

How guard results affect downstream actions in a multi-action workflow:

| on_false | Output record | Downstream actions |
|----------|--------------|-------------------|
| `skip` | Original content preserved, `metadata.reason: "guard_skip"` | **Process normally** — each action evaluates its own guard independently |
| `filter` | Record excluded from output | **Never sees it** — record is removed from every action below the filter |

An action left holding no record because its guard filtered them all is skipped, and so is every action that depends on it. With several input files, filtering all of one file's records is not enough: an action that keeps records from another file completes, and the actions that depend on it run on what it kept and hold nothing for the file it filtered, in either run mode. Records it keeps from a file the run did not read, such as one beyond `--file-limit`, count too.

### Skipped records flow downstream

When Action A skips a record (`on_false: skip`), Action B still receives it and can process it with its own LLM call. Each action's guard is independent:

```yaml
actions:
  - name: extract_facts
    dependencies: [classify]
    guard:
      condition: 'classify.status == "active"'
      on_false: "skip"       # Inactive records pass through with original content

  - name: generate_summary
    dependencies: [extract_facts]
    # Receives ALL records from extract_facts, including skipped ones
    # Can define its own guard or process everything
```

### Filtered records leave only what is below the filter

A record an action filters is gone from that action and from every action that depends on
it, directly or through others. An action on another branch, one that does not depend on
the filtering action, still receives the record, and so does one under another start node.
Where the branches meet again, in an action that depends on both, the record stays out: it
does not come back through the branch that kept it.

### Upstream failures are short-circuited

When an upstream action fails for some records (e.g., batch API errors), those records are automatically skipped by all downstream actions — no context loading, prompt rendering, or LLM calls are wasted. Each action below stores them as `cascade_skipped` with an `unprocessed` disposition, in either run mode. Its guard does not judge them: a guard reading the failed action's fields finds them null, and would otherwise skip or filter the record as if nothing had failed. These records are preserved in the output for lineage traceability, and `agac retry` sends them on through the actions below once the failed action answers them.

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
  condition: 'upstream_action.passes_filter == true'
  on_false: filter
  passthrough_on_error: false   # filter the record if evaluation fails
```

:::tip
When a guard silently lets records through unexpectedly, check `target/errors.json` for `G002` events — these indicate evaluation failures that were swallowed by `passthrough_on_error: true`.
:::

### UDF guards

A UDF guard (`condition: "udf:name"`) passes its record when the function raises, with the one exception below, the same as `passthrough_on_error: true` on a SQL guard; set `passthrough_on_error: false` to skip the record instead — a UDF condition only supports `on_false: skip`, so that is the behavior a raise applies. The function is handed a read-only view of the record, so the record cannot be changed from inside a guard. Assigning to it, or calling a method that writes to it, raises, and that one error is not passed through: the function gave no answer, so the action stops with an error naming the function, and no record reaches it unjudged. A function that catches the refusal and carries on still decides, but an error it raises while handling the refusal (inside the `except` that caught it) counts as the write, and the message names that error too. Under `run_mode: batch`, a write stops the action this way when it happens in the check run before submitting (the first rows, up to the first one the guard admits) or on any record the run carries as done from an earlier run, which the guard judges again before anything is sent; a write on another row fails that record alone. To work on a value, copy it before writing to it (`data["ns"].copy()` is deep and writable) and return the answer.

## Common Mistakes

### Unquoted String Literals

String values on the right-hand side of comparisons **must be quoted**. Unquoted strings are treated as field references and produce a preflight validation error:

```yaml
# WRONG — "approved" is interpreted as a field name
guard:
  condition: 'review_report.hitl_status == approved'

# CORRECT — quote string literals
guard:
  condition: 'review_report.hitl_status == "approved"'
```

## Limitations

- **No external calls** - Guards can't make API requests
- **Limited functions** - Only built-in functions available
- **File granularity pre-filter** - With File granularity, guards run as a per-record pre-filter before the action receives the array
- **Single expression** - Complex logic should use tool actions

## Guards with File Granularity

When a guard is configured on a File-granularity action (tool or HITL), the guard evaluates per-record as a **pre-filter** before the action receives the data array.

```yaml
- name: deduplicate_active
  dependencies: [upstream_action]
  kind: tool
  granularity: file
  impl: deduplicate
  guard:
    condition: 'upstream_action.status == "active"'
    on_false: filter  # Only active records sent to dedup tool
```

### Behavior

| `on_false` | Passing records | Failing records |
|------------|----------------|-----------------|
| `filter` | Sent to action | Removed from this action and every action below it |
| `skip` | Sent to action | Preserved in output with original content |

The action only sees records that pass the guard. This is useful for:
- **HITL**: Show only flagged records to the reviewer (see [Pattern 4: Pre-filtered HITL Review](../../guides/human-in-the-loop.md#pattern-4-pre-filtered-hitl-review))
- **Tools**: Process only qualifying records (e.g., deduplicate only active items)

## See Also

- [Context Scope](../context/context-scope) - Field visibility
- [Granularity](./granularity) - Record vs file processing
