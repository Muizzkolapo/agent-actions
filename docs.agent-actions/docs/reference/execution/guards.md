---
title: Guards
sidebar_position: 1
---

# Guards

A guard examines a condition for each record. The result decides if the action runs for that record. Thus guards are quality checkpoints in your workflow.

## Syntax

```yaml
- name: my_action
  guard:
    condition: "expression"
    on_false: "skip" | "filter" | "warn"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `condition` | string | Required | The expression that the guard examines against the upstream data |
| `on_false` | string | `filter` (SQL) / `skip` (UDF) | The result when the condition is false. **The default depends on the guard type.** The default for SQL-style guards is `filter`. The default for UDF guards is `skip`. |
| `passthrough_on_error` | boolean | `true` | If the evaluation fails, let the record continue |

## on_false Options

| Value | Description |
|----------|-------------|
| `skip` | The action does not run. The record continues to the downstream actions, with its original content. |
| `filter` | The framework removes the record from the action output fully. The downstream actions never see it. |
| `warn` | The record continues to LLM processing as usual. The framework logs a warning. |

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

`not` binds less tightly than all comparison operators, and more tightly than `and`/`or`:

- `not x == 1` negates the comparison. It reads as `not (x == 1)`.
- `not x == 1 and y == 2` reads as `(not (x == 1)) and (y == 2)`.
- On a field alone, `not x` negates the truthiness of the field.

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

Each field has its action prefix. All guard fields must have this prefix. See
[Context Access](#context-access).

`BETWEEN` includes the two ends of its range. Thus the example keeps a score of 50 and a score of
100. You can also write the range as a list, `score_review.score BETWEEN [50, 100]`. The
two forms have the same meaning. The ends are two numbers or two quoted strings, written in the
clause. Before the run starts, the framework refuses a clause that does one of these things:

- It gives only one end (`BETWEEN 50`).
- It gives `NULL` or a boolean for an end.
- It names a field for an end (`BETWEEN limits.low AND limits.high`).

To keep the values outside a range, write `NOT BETWEEN`. Alternatively, put the range in
parentheses: `NOT (score_review.score BETWEEN 50 AND 100)`.

`LIKE` and `NOT LIKE` use SQL wildcards, not a glob. `%` is any sequence of characters. `_` is
exactly one character. All other characters, `*` included, are literal. The pattern must match the full
value. The match ignores case. No escape is available for a literal `%` or `_`. The example keeps
`prod_east` and `PROD_WEST`. `"prod_*"` would keep only a name of six characters that ends in a literal `*`.

### Functions

| Function | Example |
|----------|---------|
| `LENGTH` | `LENGTH(extract.items) > 2` |
| `UPPER` | `UPPER(classify.category) == "SPAM"` |
| `LOWER` | `LOWER(classify.category) == "spam"` |
| `TRIM` | `TRIM(summarize.title) != ""` |

Each function takes exactly one argument: a field, a string, a number, a boolean or `NULL`. It returns a
plain value that a comparison can use. A function call is not a valid argument. Thus the functions do
not nest, and the framework refuses `LENGTH(TRIM(x))`. `LENGTH` counts the characters of a string or the items of a list.
For a value that is not a string and not a list, `LENGTH` uses the string form of the value. `NULL` has the length `0`. A field
in a function still needs its action prefix, exactly as it does outside a function.

Guard functions are not available in an `expression` [expectation](../validation/expectations.md#expressions)
condition. That condition uses the same grammar. But it examines the output of its own action, not a
stored record.

Be careful with `IS NULL`. If `IS NULL` cannot resolve a prefixed name, for example a misspelling, it
uses null for that name. Thus the clause is true and the record passes. All other operators
report a missing field and filter the record. Only `IS NULL` lets the record continue, and it logs nothing when it does this.
Preflight refuses a field that has no prefix. It also refuses the misspellings that it can prove
(see [Context Access](#context-access)).
For example, preflight refuses `summarize.descriptio IS NULL` when the schema of `summarize` lists its fields. Preflight cannot prove the
misspelling for an action that has no schema, or for an action whose schema sets `additionalProperties`. In that case,
it warns `Cannot validate field 'descriptio'`, and the guard passes all records.

A guard can be on a `source.` field that no staged record holds. This guard can be on the first action or on any downstream action.
When the run reads the staged file, it logs a warning:

`Action 'tag' guards on source.scroe, but no record staged from staging/rows.json holds 'scroe'.`

The run continues, and the guard decides what occurs to each record.

### Boolean Values

Boolean keywords are not case-sensitive. This agrees with the SQL convention:

```yaml
guard:
  condition: 'upstream_action.passes_filter == true'   # valid
  condition: 'upstream_action.passes_filter == True'   # valid
  condition: 'upstream_action.passes_filter == TRUE'   # valid
```

For boolean fields, use an explicit comparison, not a bare field reference. A bare reference uses Python truthiness. This fails silently when the upstream action stores `"false"` as a string (which is truthy), not as a Python `bool`:

```yaml
# Fragile — string "false" is truthy, so the guard never filters
condition: 'upstream_action.passes_filter'

# Explicit — matches a real boolean only; a string field needs a quoted string
condition: 'upstream_action.passes_filter == true'
condition: 'upstream_action.passes_filter_text == "true"'
```

`== true` is false for the string `"true"`. Thus a guard of this type on a string field that holds `"true"` filters all records.

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

A guard controls the action before the action receives data. Thus the guard reads the record **as stored**.
It reads all namespaces that the record carries, with the address `action_name.field`. A record carries the
actions upstream of it through `dependencies`. Thus a clause names only those actions. Preflight refuses
a guard that names one of these actions:

- An action that runs at the same time as its own action, or after it.
- An action on a parallel branch.
- Its own action. The guard runs before the action, so the output of the action is not on the record yet.

Preflight checks each `action_name.field` in a clause in the same way that it checks the references of a prompt.
It refuses a name that is not an action in the workflow. If a name is near, preflight suggests the closest name.
It also refuses a field that the schema of the action does not list. It then names the field that
you probably meant, or the fields that the schema has. The namespace of an action holds the data that the action produced,
and the `expect` verdict that its expectations attach. It does not hold the data that the action observes or passes through. Thus preflight also refuses a
guard that names one of those fields under the action. Without
this check, such a guard would filter all records, and the run would report success. You read a versioned
action by its branch names, `vote_1.vote` and `vote_2.vote`. Its base name `vote` is on
no record. Thus preflight refuses it and names the branches.

Preflight cannot check some fields. These are the fields of
an action that has no schema, and the fields that its schema admits with `additionalProperties` but does not list.
Preflight gives a warning for these fields and does not refuse them. `source.*`, `seed.*`, `workflow.*`, version params
and the `output_field` of a dependency are not action names. Preflight does not check them as actions.

| Source | Syntax |
|--------|--------|
| A staged field, on the first action | `source.page_content` |
| A field of an upstream action | `extract_facts.count` |
| A field of a dependency, if the action observes it or not | `group_by_similarity.num_similar_facts` |
| The declared [seed data](../context/seed-data.md) of the action | `seed.thresholds.min_score` |

The guard of the first action reads the staged record under `source`, as its prompt does. A staged
field without the prefix, `page_content == 'two'`, names no field that the guard can read.
Thus preflight refuses it and names `source.page_content`.

A guard reads the seed data that its action declares under `context_scope.seed`. This is the same data
that the prompt of the action reads. Thus `seed.thresholds.min_score >= 0.5` reads a value from a
reference file.

A clause compares a field with a literal value or with another field.
`score_review.score >= seed.thresholds.min_score` and `extract.score < extract.limit` both
work. Preflight checks a field on the right in the same way as a field on the left. Thus preflight refuses a misspelled
action name, schema field or seed key on the two sides. A field on the right needs
its prefix, as on the left. Preflight reads a name with no dot on the right as an
unquoted string, and refuses it. `status == approved` gives
`compares field 'status' to bare identifier 'approved'`. A record that does not have a field on
one of the two sides does not match. Thus `on_false` decides what occurs to that record.

The guard can see all declared seed keys. This includes
a seed key that the action `drop`s. Preflight refuses a guard that reads a seed key that its action does not
declare. It also refuses a prompt that reads such a seed key.

`context_scope` describes the data that the action receives after the guard lets the record continue.
It does not decide the verdict. A field that the action `drop`s still answers a clause. The
guard field does not have to be in `observe`.

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

This table shows how guard results change the downstream actions in a workflow that has many actions:

| on_false | Output record | Downstream actions |
|----------|--------------|-------------------|
| `skip` | The original content stays, `metadata.reason: "guard_skip"` | **Process as usual** — each action examines its own guard independently |
| `filter` | The framework removes the record from the output | **Never see the record** — the framework removes the record from each action downstream of the filter |

If a guard filters all of the records of its action, the action holds no record. The framework skips that action and each action that depends on it. With several input files, a filter on all records of one file is not sufficient. These results occur in the two run modes:

- An action that keeps records from another file completes.
- The actions that depend on it run on the records that it kept. They hold nothing for the file that it filtered.

The records that the action keeps from a file that the run did not read also count. An example is a file after the `--file-limit`.

### Skipped records flow downstream

When Action A skips a record (`on_false: skip`), Action B still receives the record. Action B can process the record with its own LLM call. The guard of each action is independent:

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

When an action filters a record, the record is removed from that action. It is also removed from each action that depends on
that action, directly or through other actions. An action on another branch still receives the record, if it does not depend on
the action that filters. An action under another start node also receives the record.
The branches can meet again in an action that depends on the two branches. In that action, the record stays out. It
does not come back through the branch that kept it.

### Upstream failures are short-circuited

When an upstream action fails for some records (for example, batch API errors), all downstream actions skip those records automatically. The framework uses no resources on context loading, prompt rendering or LLM calls for them. Each downstream action stores them as `cascade_skipped` with an `unprocessed` disposition, in the two run modes. Its guard does not examine them. A guard that reads the fields of the failed action finds them null. Without this rule, the guard would skip or filter the record as if no failure occurred.

The framework keeps these records in the output, so that you can trace their lineage. When the failed action processes them, `agac retry` sends them through the downstream actions.

## Error Handling

The framework puts guard evaluation errors into three categories. It handles each category differently:

| Category | Example | `passthrough_on_error` respected? | Behavior |
|----------|---------|-----------------------------------|----------|
| **Semantic** | Unquoted string (`status == approved`) | No — always uses `on_false` | The condition is broken. The framework caches the result after the first occurrence. |
| **Missing field** | `upstream_action.field` is not in this record | No — the condition is not met, so `on_false` applies | The framework logs a `G002` event. |
| **Data** | Any other error that occurs while the guard examines this record | Yes | A failure that applies only to this record |
| **Timeout** | The evaluation took more time than the time limit | Yes | A transient failure |

**Semantic errors** ignore `passthrough_on_error`, because the condition is fully broken. If the records continued, the results would be wrong for all records, not only for one record. The framework logs these errors one time (circuit breaker), not for each record.

**Data errors and timeout errors** obey `passthrough_on_error` (default: `true`). To apply the configured `on_false` behavior, set it to `false`:

```yaml
guard:
  condition: 'upstream_action.passes_filter == true'
  on_false: filter
  passthrough_on_error: false   # filter the record if evaluation fails
```

:::note
Each `G002` event in `agent_io/logs/errors.json` is an evaluation failure, and a missing field is one type. A missing field applies `on_false`. When `passthrough_on_error` is `true`, other data errors pass the record.
:::

When a guard does not do what you expect, look for `G002` events in `agent_io/logs/errors.json` in the workflow folder.

### UDF Guards

A UDF guard (`condition: "udf:name"`) passes its record when the function raises an error. This is the same as `passthrough_on_error: true` on a SQL guard. There is one exception, which this section gives below. To skip the record in this case, set `passthrough_on_error: false`. A UDF condition supports only `on_false: skip`. Thus a skip is the behavior that an error applies.

The function receives a read-only view of the record. Thus a guard cannot change the record. The view raises an error when the function assigns a value to it. The view also raises an error when the function calls a method that writes to it. The guard does not pass that one error through. The function gave no answer. Thus the action stops with an error that names the function, and no record gets to the action without a verdict.

A function that catches the refusal and continues still decides. But an error that it raises while it handles the refusal (in the `except` that caught it) counts as the write. The message also names that error.

Under `run_mode: batch`, a write stops the action in this way at each of these points:

- In the check run before the submission (the first records, up to the first record that the guard admits).
- On a later record that the run prepares for submission.
- On a record that the run carries as done from an earlier run. The guard examines it again before the run sends data.
- During the preparation of a retry round.

To work on a value, copy it before you write to it (`data["ns"].copy()` is deep and writable). Then return the answer.

## Common Mistakes

### Unquoted String Literals

You **must put quotes** around string values on the right side of comparisons. Preflight reads an unquoted string as a field reference and gives a validation error:

```yaml
# WRONG — "approved" is interpreted as a field name
guard:
  condition: 'review_report.hitl_status == approved'

# CORRECT — quote string literals
guard:
  condition: 'review_report.hitl_status == "approved"'
```

## Limitations

- **No external calls** - Guards cannot make API requests.
- **Limited functions** - Only `LENGTH`, `UPPER`, `LOWER` and `TRIM`.
- **File granularity pre-filter** - With File granularity, a guard is a pre-filter for each record. It runs before the action receives the array.
- **One expression** - Complex logic should use tool actions.

## Guards with File Granularity

A guard on a File granularity action (tool or HITL) is a **pre-filter**. It examines each record before the action receives the data array.

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
| `filter` | The framework sends them to the action | The framework removes them from this action and from each downstream action |
| `skip` | The framework sends them to the action | The framework keeps them in the output, with the original content |

The action sees only the records that pass the guard. This behavior helps in these cases:

- **HITL**: Show only flagged records to the reviewer (see [Pattern 4: Pre-filtered HITL Review](../../guides/human-in-the-loop.md#pattern-4-pre-filtered-hitl-review)).
- **Tools**: Process only the records that agree with the condition (for example, deduplicate only active records).

## See Also

- [Context Scope](../context/context-scope) - Field visibility
- [Granularity](./granularity) - Record processing and file processing
