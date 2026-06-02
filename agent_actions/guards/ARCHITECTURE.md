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
guard: "udf:tools.check_eligibility"   # UDF — defaults to on_false: skip

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

User-defined Python functions referenced by module path. The function receives the record data and returns a boolean.

```yaml
guard:
  condition: "udf:tools.guards.check_eligibility"
  on_false: skip
```

Validated at parse time: must match `module.function` dotted path format, checked against `DANGEROUS_PATTERNS_UDF`. UDF guards **cannot use FILTER behavior** — this is enforced during config expansion in `expander_action_types.py`, which raises `ConfigurationError` if a UDF guard specifies `on_false: filter`.

### Safety Validation

Both types run through safety checks at parse time:

- SQL expressions: blocked patterns include `exec(`, `eval(`, `__import__`, `system(`, `subprocess`
- UDF expressions: same checks plus format validation (must be `module.function` or `module.submodule.function`)
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
│      validates UDF format (module.function)                  │
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
│      UDF  → agent["conditional_clause"] = "module.func"      │
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

10. **Legacy UDF path (conditional_clause) is separate from the guard dict path.** When a UDF guard is expanded, it sets `agent["conditional_clause"]` instead of `agent["guard"]`. The evaluator handles this in `_evaluate_conditional_clause()`, which swallows exceptions and proceeds (never skips on UDF error). The SQL guard path goes through `_evaluate_guard()` with full error classification.
