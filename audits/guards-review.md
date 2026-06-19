# Code Review: agent_actions/guards/

**Date:** 2026-06-17
**Reviewer:** Claude (single-angle deep review)
**Files reviewed:** 3 Python files + 1 caller (evaluator.py)

---

## Findings

### 1. CONFIRMED — Silent fallback: UDF guard exceptions bypass guard protection

- **File:** `agent_actions/input/preprocessing/filtering/evaluator.py:205`
- **Summary:** `_evaluate_conditional_clause()` catches ValueError/TypeError/KeyError/AttributeError from UDF execution, logs at DEBUG only, returns None. evaluate() falls through to _evaluate_guard(), which returns GuardResult.passed() if no guard_config exists. A broken UDF guard silently becomes a no-op.
- **Failure scenario:** UDF guard function has a bug (raises KeyError). Guard silently passes. Records that should be filtered proceed through the pipeline unprotected.
- **Severity:** HIGH — silent fallback, guard fails open

### 2. CONFIRMED — Cross-format default inconsistency for on_false

- **File:** `agent_actions/guards/consolidated_guard.py:89`
- **Summary:** `from_dict()` defaults missing `on_false` to "filter" for all guard types. `from_string()` defaults UDF strings to SKIP and SQL strings to FILTER. Dict-form UDF guard gets FILTER by default, which then hits ConfigurationError in expander_action_types.py.
- **Failure scenario:** User writes `{"condition": "udf:validators.check"}` without `on_false`. Gets FILTER default. expander_action_types.py:33 raises ConfigurationError about FILTER not being valid for UDF guards — error message gives no hint the implicit default caused the problem.
- **Severity:** MEDIUM — user-hostile trap

### 3. CONFIRMED — Docstring falsely claims safe column names won't trigger validator

- **File:** `agent_actions/guards/guard_parser.py:42`
- **Summary:** parse() docstring says column names like 'file', 'input', 'vars', 'dir' "will not trigger the dangerous-pattern validator". They do — word-boundary regex matches standalone tokens.
- **Failure scenario:** User writes `file == "pdf"` guard, gets ValidationError. Docstring said this would work.
- **Severity:** MEDIUM — incorrect documentation causes user confusion

### 4. CONFIRMED — Double parse in from_string()

- **File:** `agent_actions/guards/consolidated_guard.py:96`
- **Summary:** from_string() calls GuardParser.parse() for type detection, then cls() constructor calls parse() again. First result discarded.
- **Severity:** LOW — dead work, no correctness impact

---

## Recommended fix priority

| Priority | Findings | Effort |
|----------|----------|--------|
| P0 (silent fallback) | #1 — UDF guard bypass | Medium — raise or log at warning, don't return None |
| P1 (user trap) | #2 — on_false default inconsistency | Small — align defaults |
| P1 (docs) | #3 — false docstring | Small — fix docstring or fix regex |
| P3 | #4 — double parse | Small — pass parsed result through |
