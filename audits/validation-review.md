# Code Review: agent_actions/validation/

**Date:** 2026-06-17
**Reviewer:** Claude (single-angle deep review)
**Files reviewed:** 48 Python files

---

## Findings

### 1. CONFIRMED — _apply_context_scope reads nonexistent top-level keys, producing empty observe/drop sets

- **File:** `agent_actions/validation/static_analyzer/schema_extractor.py:401`
- **Summary:** Reads `config.get('observe')` and `config.get('drops')` from action top-level dict. These keys don't exist at the top level (they live under `context_scope`). All actions get empty observe_fields and dropped_fields. All downstream static checks (guard-nullable, drop-directive) produce zero findings.
- **Failure scenario:** Action with `context_scope: { drop: [upstream.sensitive_field] }` → dropped_fields = set() → drop-directive check passes → guard using dropped field not caught.
- **Severity:** HIGH — systematic false negatives in static analysis

### 2. CONFIRMED — Unhandled TimeoutError from as_completed() in key_verifier

- **File:** `agent_actions/validation/preflight/key_verifier.py:195`
- **Summary:** `for future in as_completed(futures, timeout=7)` raises TimeoutError if slow probes exceed wall-clock limit. Not caught anywhere. Crashes entire preflight run.
- **Failure scenario:** 4 vendor probes on slow DNS, each ~4.8s → as_completed timeout at 7s → unhandled TimeoutError → preflight crash → workflow won't start.
- **Severity:** HIGH — unhandled exception crashes preflight

### 3. CONFIRMED — Bare except Exception swallows prompt file errors in resolution_service

- **File:** `agent_actions/validation/preflight/resolution_service.py:461`
- **Summary:** `_resolve_prompt_for_extraction` catches all exceptions and returns original config string. Any prompt file error (YAML parse error, encoding error) silently skips template-level seed field validation.
- **Failure scenario:** Prompt file has Jinja syntax error → swallowed → seed field references never validated → discovered only at runtime.
- **Severity:** MEDIUM — silent fallback, validation bypass

### 4. CONFIRMED — check_missing_dependencies() is dead code

- **File:** `agent_actions/validation/static_analyzer/type_checker.py:243`
- **Summary:** Method detects actions referencing upstream data without declaring dependency. Never called by WorkflowStaticAnalyzer.analyze(). Implicit dependency bugs never caught statically.
- **Severity:** MEDIUM — validator exists but unused

### 5. CONFIRMED — _check_api_keys() format-mismatch warnings list always empty

- **File:** `agent_actions/validation/preflight/resolution_service.py:177`
- **Summary:** Docstring says "Format mismatches are warnings" but the method body never populates the warnings list. Key-format validation promised but not implemented.
- **Failure scenario:** Wrong API key in wrong env var (Groq key in ANTHROPIC_API_KEY) → no format warning → discovered at runtime.
- **Severity:** MEDIUM — missing advertised validation

### 6. CONFIRMED — output_field validator error message misleading for missing json_mode

- **File:** `agent_actions/validation/action_validators/granularity_output_field_validator.py:53`
- **Summary:** json_mode defaults to True when omitted. User with `output_field` but no explicit json_mode gets "output_field can only be used when json_mode is false" instead of a helpful message to add json_mode: false.
- **Severity:** LOW — confusing error message

---

## Recommended fix priority

| Priority | Findings | Effort |
|----------|----------|--------|
| P0 (systematic false negatives) | #1 (context_scope key mismatch) | Small — read from context_scope sub-dict |
| P0 (crash) | #2 (TimeoutError unhandled) | Small — catch and degrade gracefully |
| P1 (silent fallback) | #3 (prompt error swallowed) | Small — narrow catch or log at warning |
| P1 (dead validator) | #4 (check_missing_dependencies) | Small — wire into analyze() |
| P2 (missing feature) | #5 (format-mismatch warnings) | Medium — implement or remove docstring promise |
| P3 (UX) | #6 (error message) | Small — improve message |
