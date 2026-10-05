# Guards Module Architecture

This document maps `agent_actions/guards/` — a leaf package that parses and validates guard expressions from workflow config. Guards control whether individual records are processed by an action, skipped with a tombstone, or excluded entirely.

---

## High-Level Overview

```
agent_actions/guards/          ← THIS PACKAGE (config-time parsing)
├── guard_parser.py            Parse string → GuardExpression (SQL or UDF)
└── consolidated_guard.py      Parse string-or-dict → GuardConfig (expression + behavior)

input/preprocessing/filtering/ ← EVALUATION LAYER (runtime)
├── evaluator.py               GuardEvaluator — runs guard against record data
└── guard_filter.py            GuardFilter — AST eval, caching, timeout, circuit breaker

output/response/
└── expander_action_types.py   Expands guard config into agent dict at config time
```

The package has **two files** and **no state**. It exists as a separate leaf package to break a circular import between `config/` (which reads guard definitions) and `output/` (which expands them into agent dicts). Both `guards/` modules depend only on `errors` and `utils.constants`.

---

## Two Input Formats

Guard configuration in `agent_config/{workflow}.yml` supports two formats:

```yaml
# Legacy string format
guard: "status == 'active'"            # SQL — defaults to on_false: filter
guard: "udf:check_eligibility"         # UDF — defaults to on_false: skip

# Current dict format
guard:
  condition: "status == 'active'"
  on_false: skip                       # explicit behavior control
```

`parse_guard_config()` is the single entry point. It dispatches to `GuardConfig.from_string()` (legacy) or `GuardConfig.from_dict()` (current). The legacy path assigns default behaviors: SQL guards default to FILTER, UDF guards default to SKIP.

---

## Guard Types

### SQL Guards

SQL-like boolean expressions evaluated against record data using an AST parser. Supports comparison operators, logical operators (AND/OR/NOT), IS NULL, IN, LIKE, and dotted field paths for namespaced content.

```yaml
guard:
  condition: "validate.pass == true AND score > 0.8"
```

Validated at parse time against `DANGEROUS_PATTERNS` (blocks `exec`, `eval`, `__import__`, etc.). No actual SQL engine is involved — the AST evaluator in `input/preprocessing/filtering/` handles execution.

### UDF Guards

User-defined Python functions referenced by name. The function receives the guard context and returns a boolean.

```yaml
guard:
  condition: "udf:check_eligibility"
  on_false: skip
```

The name is the registered function's own, with no module prefix — the same form `impl:` uses, because both resolve through `UDF_REGISTRY`, which is keyed on `f.__name__.lower()`. A dotted path is refused: it matches no registry key, and the preflight static checker reads the dot as an action reference (#1188). `agac list-udfs` prints the registered names.

Validated at parse time: must be a Python identifier, checked against `DANGEROUS_PATTERNS_UDF`. UDF guards **cannot use FILTER behavior** — this is enforced during config expansion in `expander_action_types.py`, which raises `ConfigurationError` if a UDF guard specifies `on_false: filter`.

### Safety Validation

Both types run through safety checks at parse time:

- SQL expressions: blocked patterns include `exec(`, `eval(`, `__import__`, `system(`, `subprocess`
- UDF expressions: same checks plus format validation (must be a Python identifier — the registered function's own name, no module prefix)
- Built-in Python names (`file`, `input`, `vars`, `dir`) are treated as column references in SQL guards, not as Python builtins

---

## Guard Behaviors

Three behaviors control what happens when a guard condition evaluates to false:

```
FILTER  Record is excluded entirely. No output row is written.
        The record does not appear in agent_io/target/{action}/.
        In batch mode, the context_map marks it as FILTERED.

SKIP    Record is not sent to the LLM, but a tombstone disposition
        is written to storage. The record appears in output with its
        original content (passthrough) but no LLM-generated fields.

WARN    Record proceeds to LLM processing normally. A warning is
        logged but execution is not blocked. The record is treated
        as if the guard passed.
```

Unsupported behaviors (`write_to`, `reprocess`) are recognized during config loading but rejected with `ConfigValidationError`.

---

## Full Evaluation Pipeline

```
┌──────────────────────────────────────────────────────────────┐
│ 1. CONFIG VALIDATION (parse time)                            │
│                                                              │
│    agent_config/{workflow}.yml                                │
│    guard: "status == 'active'"                               │
│         │                                                    │
│         ▼                                                    │
│    parse_guard_config()  →  GuardConfig                      │
│      validates expression safety (dangerous patterns)        │
│      validates UDF format (bare function name)               │
│      validates behavior (skip/filter/warn)                   │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│ 2. EXPANSION (config expansion)                              │
│                                                              │
│    expander_action_types.py :: process_guard_config()         │
│                                                              │
│    Converts GuardConfig into agent dict keys:                │
│      SQL  → agent["guard"] = {clause, scope, behavior}       │
│      UDF  → agent["conditional_clause"] = "func_name"        │
│                                                              │
│    Enforces: UDF cannot use FILTER behavior                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│ 3. TASK PREPARATION (per-record, before LLM call)            │
│                                                              │
│    processing/task_preparer.py :: TaskPreparer.prepare()      │
│                                                              │
│    For each record:                                          │
│      load field_context (upstream outputs, seed data)        │
│      call GuardEvaluator.evaluate(item, guard_config)        │
│      result → INCLUDED / FILTERED / SKIPPED                  │
│                                                              │
│    Filtered/skipped records get a PreparedTask with          │
│    guard_status set; they are never sent to the LLM.         │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│ 4. GUARD EVALUATOR (runtime evaluation)                      │
│                                                              │
│    input/preprocessing/filtering/evaluator.py                │
│      GuardEvaluator.evaluate()                               │
│        │                                                     │
│        ├─ _prepare_eval_context()                            │
│        │    promotes content namespaces to top-level keys     │
│        │    {"content": {"action_a": {"f": 1}}}              │
│        │       → {"action_a": {"f": 1}}                      │
│        │                                                     │
│        ├─ _evaluate_conditional_clause() (legacy UDF path)   │
│        │    calls execute_user_defined_function()             │
│        │                                                     │
│        └─ _evaluate_guard() (SQL path)                       │
│             builds FilterItemRequest                         │
│             calls GuardFilter.filter_item()                  │
│             reclassifies missing-field errors                │
│             maps FilterResult → GuardResult                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│ 5. GUARD FILTER (AST evaluation engine)                      │
│                                                              │
│    input/preprocessing/filtering/guard_filter.py             │
│      GuardFilter.filter_item()                               │
│        │                                                     │
│        ├─ circuit breaker check (semantic error cache)       │
│        ├─ submit to ThreadPoolExecutor (timeout protection)  │
│        ├─ parse condition (LRU cached)                       │
│        └─ AST evaluate against record data                   │
│                                                              │
│    Returns FilterResult with:                                │
│      success, matched, error, error_category, execution_time │
└──────────────────────────────────────────────────────────────┘
```

---

## Error Classification

Guard evaluation errors fall into three categories, each with different handling:

```
SEMANTIC    The condition itself is broken (unquoted string literal,
            syntax error, invalid operator). Bypasses passthrough_on_error
            — the guard behavior always applies. Circuit-breaker caches
            these so the same broken condition is not re-evaluated.

DATA        A field referenced in the condition does not exist in this
            particular record. Respects passthrough_on_error: if true,
            the record passes through; if false, the guard behavior
            applies. Missing fields in namespaced content may be
            reclassified (see reclassify_missing_field_error).

TIMEOUT     Evaluation exceeded the time limit (default 5 seconds).
            Treated like a DATA error for passthrough_on_error purposes.
```

### passthrough_on_error

A per-guard config flag (default: `true`). When `true`, DATA and TIMEOUT errors cause the record to pass through as if the guard matched. When `false`, the configured behavior (filter/skip/warn) applies on error.

SEMANTIC errors **always bypass** `passthrough_on_error` — a broken condition is a config bug, not a data issue, and should not silently pass records through.

---

## Record Disposition After Guard

```
Guard matched (true)     → record proceeds to LLM
Guard not matched:
  FILTER behavior        → no output row written, no tombstone
                           batch context_map: _batch_filter_status = "filtered"
  SKIP behavior          → tombstone disposition written to storage
                           record appears in output with original content
  WARN behavior          → warning logged, record proceeds to LLM
```

In batch mode, filtered records are marked in the context_map during preparation and never submitted to the provider. The disposition must be explicitly written during batch finalization. In online mode, the disposition is written immediately by the result collector.

---

## Batch vs Online Timing

```
BATCH:
  Guards run in Phase 1 (preparation), BEFORE provider submission.
  Filtered/skipped records are marked in context_map.
  They never appear in the JSONL file sent to the provider.
  Dispositions are written during finalization.

ONLINE:
  Guards run per-record in task_preparer, BEFORE the LLM call.
  Filtered/skipped records get immediate disposition writes.
  No context_map involved — state is in-memory only.
```

The guard evaluation code is identical in both paths — `GuardEvaluator` is used by both `TaskPreparer` (online) and the batch preparator. The difference is only in when dispositions are persisted.

---

## Evaluation Context

What the guard condition sees at evaluation time:

```
Raw record from storage:
  {
    "source_guid": "abc",
    "content": {
      "extraction": {"title": "Report", "score": 0.9},
      "validation": {"pass": true}
    },
    "_passthrough_fields": {"name": "Alice"}
  }

After _prepare_eval_context() promotes namespaces:
  {
    "source_guid": "abc",
    "extraction": {"title": "Report", "score": 0.9},
    "validation": {"pass": true},
    "_passthrough_fields": {"name": "Alice"}
  }

Guard condition uses dotted paths:
  extraction.score > 0.8 AND validation.pass == true
```

If `_build_evaluation_context()` is used (Phase 2 evaluation with full context), the item's content is merged with context data (passthrough fields, source data). Content fields take precedence over top-level fields on collision.

A framework namespace — `source`, `version`, `workflow`, `seed` — is the exception, and a narrow one: **where the context resolved a namespace and the record carries a namespace under the same name, the resolved one wins.** A record's copy was taken when the record was written and the pool can have moved past it, so the resolved answer is the run's current one. Without this a guard read the carried copy, and the same clause answered differently depending on whether a `context_scope` pass had already written the resolved namespace onto the record.

Both sides must be a namespace. These are reserved **action** names, which does not make a plain field spelled that way the framework's, and three things put one there:

- a first-stage record's content is the user's own staging row, so `source` can be a string they staged — and first-stage resolution builds the namespace *out of that same content*, so the key is present on both sides;
- a version-merge **tool**'s output is spread flat over content rather than nested under the action name, so `version` or `source` can be that tool's own output field — refused now where the action's schema declares such a field, and reported where it replaces a key, but the shape still arrives from a tool that declares no output schema;
- a dependency's `output_field` is promoted into the context by name, so a key being present in the context does not mean a resolver produced it.

Comparing shapes rather than names keeps all three: a scalar is somebody's field and is left alone. Removing such a key would leave the clause reading a missing field, which `reclassify_missing_field_error` turns into *not matched* — a silent filter rather than an error.

Two consequences worth stating:

- **`context_scope` does not decide a guard's verdict.** A guard gates the action before it receives anything, so it reads the record as stored and `drop` describes what the action is then handed. FILE mode applies the scope pass first, and `prefilter_by_guard` evaluates against the pre-scope records it is already given alongside — so a dropped field, in the `source` namespace or a dependency's, still answers a clause. The record handed on to the tool is still the scoped one: the scope decides what the action sees, not how it is judged. Where no originals are supplied, which is every RECORD-mode route into that function, the scoped and stored lists are the same object.

  The verdict is the limit of that guarantee. The scope pass can still remove a record before any guard runs — one whose `source` it cannot resolve, or one missing a field an `observe` names, is skipped with a disposition rather than judged. RECORD mode runs the same pass, but *after* the guard and without that rescue: an unenrichable record raises `RecordContextError` where FILE mode skips it. So which records a guard gets to judge, and what becomes of the ones it does not, still depends on granularity; a separate divergence, tracked in #1140, and not closed here.

  The narrowing that comes with reading the stored record: the scope pass also flattens an observed field to a bare top-level key for the prompt, so a clause naming one that way resolved at FILE granularity and nowhere else. It no longer resolves anywhere, and a wildcard `observe` makes that every field of the namespace, not one. Such a clause is refused rather than dropped quietly: the name has a dotted form, so `reclassify_missing_field_error` takes its suggestion branch, which logs a warning naming the supported spelling — "use dotted paths (e.g. `action_name.field`)" — and classifies SEMANTIC, which by the rule above bypasses `passthrough_on_error` and leaves the declared behaviour to apply. The same separation is visible in `run_dynamic_agent`, which takes the original data and the drop-applied data as distinct arguments and sends the applied one to the model wherever it is present — it evaluates no guard of its own (#1148).
- **No namespace key is removed, but a field can become unreadable.** The resolved document is a different document from the carried copy, so a field only the copy had reads as missing — which is *not matched*, and so a filter. That is inherent to resolving against the pool rather than against the snapshot.

---

## File Index

### Core Package (guards/)

| File | Role |
|------|------|
| `guard_parser.py` | Parse guard string into `GuardExpression` (SQL or UDF type), safety validation |
| `consolidated_guard.py` | Parse string-or-dict into `GuardConfig` (expression + behavior), behavior validation |
| `__init__.py` | Re-exports: `GuardType`, `GuardExpression`, `GuardParser`, `parse_guard`, `GuardBehavior`, `GuardConfig`, `parse_guard_config` |

### Evaluation Layer (input/preprocessing/filtering/)

| File | Role |
|------|------|
| `evaluator.py` | `GuardEvaluator` — unified guard evaluation, context preparation, error reclassification |
| `guard_filter.py` | `GuardFilter` — AST-based eval, LRU parse cache, ThreadPoolExecutor timeout, circuit breaker |

### Integration Points

| File | Role |
|------|------|
| `output/response/expander_action_types.py` | `process_guard_config()` — expands guard into agent dict keys during config expansion |
| `processing/task_preparer.py` | `TaskPreparer.prepare()` — evaluates guard per-record before LLM call |
| `workflow/executor.py` | `_compute_action_config_hash()` — includes guard clause + behavior in config hash |
| `workflow/coordinator.py` | `validate_guard_conditions()` — pre-flight AST parse and semantic checks |
| `workflow/managers/skip.py` | Action-scope guard evaluation (scope: action, not item) |
| `config/types.py` | `GuardConfig` TypedDict — `passthrough_on_error`, `passthrough_on_empty` config shape |

### Re-export Shims (backward compatibility)

| File | Role |
|------|------|
| `output/response/guard_parser.py` | Re-exports from `guards.guard_parser` |
| `output/response/consolidated_guard.py` | Re-exports from `guards.consolidated_guard` |

---

## Caveats

1. **Leaf package is intentional.** `guards/` depends only on `errors` and `utils.constants`. This breaks the `config` <-> `output` circular import that would occur if guard parsing lived in either package. Do not add dependencies on `config`, `output`, `processing`, or `input`.

2. **UDF guards cannot use FILTER behavior.** Enforced in `expander_action_types.py`, not in the guards package itself. UDF guards only support SKIP (default) and WARN. This is because UDF execution happens through `execute_user_defined_function()`, which has a different evaluation path than the AST-based SQL filter.

3. **WARN does not block execution.** A guard with `on_false: warn` logs a warning but the record proceeds to the LLM. It is observability-only — the record is treated identically to one that matched the guard.

4. **Semantic errors bypass passthrough_on_error.** If the guard condition itself is broken (syntax error, unquoted string), `passthrough_on_error: true` does not save it. The guard behavior (filter/skip/warn) always applies. This prevents silently processing records when the guard is misconfigured.

5. **Circuit breaker caches semantic errors.** `GuardFilter._semantic_error_cache` stores conditions that failed with `GuardSemanticError`. Subsequent evaluations of the same condition skip the AST entirely and return the cached error. The cache is per-`GuardFilter` instance (process-scoped singleton). Call `clear_cache()` to reset.

6. **Batch mode needs explicit disposition writing.** In batch, filtered/skipped records are marked in the context_map but dispositions are not written until finalization. If a batch run crashes between preparation and finalization, filtered records have no persisted disposition. Online mode writes dispositions immediately.

7. **Guard clause is included in the config hash.** `_compute_action_config_hash()` in `workflow/executor.py` hashes the guard clause and behavior. Changing a guard condition invalidates previously completed action results, forcing a re-run. This prevents stale results from persisting after guard logic changes.

8. **Missing fields are reclassified, not failed.** `reclassify_missing_field_error()` in `evaluator.py` handles two cases: (a) a flat field reference that exists inside a namespace is reclassified as SEMANTIC (config error); (b) a genuinely missing field is treated as "condition not matched" rather than an error. This prevents `passthrough_on_error` from accidentally passing records that should be filtered.

9. **GuardFilter uses a ThreadPoolExecutor for timeout protection.** Each evaluation runs in a thread with a configurable timeout (default 5 seconds). This prevents runaway AST evaluation from blocking the pipeline. The executor has 4 worker threads and is cleaned up via `atexit`.

10. **Legacy UDF path (conditional_clause) is separate from the guard dict path.** When a UDF guard is expanded, it sets `agent["conditional_clause"]` instead of `agent["guard"]`. The evaluator handles this in `_evaluate_conditional_clause()`, which swallows exceptions and proceeds (never skips on UDF error), except a write the read-only view refused (11). The SQL guard path goes through `_evaluate_guard()` with full error classification.

11. **A guard UDF that writes to its input stops the action.** The UDF is handed a read-only view of the record (`utils/readonly.py`, through `ReadOnlyBus`), and the view refuses a write by raising `ReadOnlyError`, a `TypeError`. Passed through like the UDF's own errors, the refusal applied no guard: the UDF gave no answer, and every record its write recurs on went to the action, with only a warning in the log. So a refusal the UDF does not swallow, one it lets escape or one it was handling when it raised (the chain is walked by `__cause__`, else `__context__`), becomes a `ConfigurationError` naming the UDF and whatever it raised in the refusal's place, marked fatal to the action. An unchained raise inside the handler counts: a handler that catches `TypeError` for its own reasons and then raises is the same guard with no answer. Fatal because the pre-filter, which every online action goes through, cannot fail one record, and a file's failure is otherwise taken alone: that file's records went missing while the action completed. Batch evaluates the guard while preparing what it submits. The check it runs first, on the leading rows up to the first one the guard admits (five at most), fails the action the same way; a later row whose guard writes is failed on its own, as preparation fails a row for any error. A UDF that catches the refusal and carries on decides as usual, and any other error the UDF raises still passes the record.
