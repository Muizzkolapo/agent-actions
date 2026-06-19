# Code Review: agent_actions/output/

**Date:** 2026-06-17
**Reviewer:** Claude (single-angle deep review)
**Files reviewed:** 19 Python files

---

## Findings

### 1. CONFIRMED — FileWriteError never raised — operation name mismatch

- **File:** `agent_actions/output/writer.py:47-73`
- **Summary:** handle_file_error checks `operation.lower() in ['write', 'save', 'create']` but operations passed are 'Write staging file', 'Write target file', etc. — none match. All OSError write failures raised as ProcessingError instead of FileWriteError.
- **Failure scenario:** Disk full during write_target → ProcessingError raised → caller catching FileWriteError misses it → no retry or disk-full handling.
- **Severity:** HIGH — wrong exception type for all file writes

### 2. CONFIRMED — Silent fallback on dispatch_task() resolution failure

- **File:** `agent_actions/output/response/dispatch_injection.py:61-68,107-113`
- **Summary:** Resolution failures caught as (ValueError, TypeError, KeyError, AgentActionsError), raw unresolved dispatch_task() string passed to LLM vendor. Comment says "may cause API errors".
- **Failure scenario:** Misconfigured dispatch_task → raw string 'dispatch_task(build_options)' sent as schema property → vendor rejects or produces malformed output.
- **Severity:** HIGH — silent fallback, broken schema sent to API

### 3. CONFIRMED — JSON Schema 'required' list treated as boolean

- **File:** `agent_actions/output/response/schema_conversion.py:63-98`
- **Summary:** `is_required = json_schema.get('required', True)` reads top-level 'required' which is a list of property names, not boolean. Non-empty list → truthy → always required. Empty list → falsy → never required.
- **Failure scenario:** Array schema with `required: [fact, paraphrase]` → outer field unconditionally required regardless of intent.
- **Severity:** MEDIUM — type confusion in schema compilation

### 4. CONFIRMED — write_target always reports 0 bytes_written

- **File:** `agent_actions/output/writer.py:110-136`
- **Summary:** bytes_written hardcoded to 0 for target writes. FileWriteCompleteEvent always shows 0 bytes. Cannot distinguish normal write from data loss via metrics.
- **Severity:** MEDIUM — broken observability

### 5. CONFIRMED — ConfigValidationError swallowed as "vendor doesn't support schemas"

- **File:** `agent_actions/output/response/context_data.py:153-161`
- **Summary:** _compile_schema_for_vendor catches ConfigValidationError for both "vendor unsupported" and any future schema compilation logic error. Real validation errors silently drop the schema constraint.
- **Severity:** MEDIUM — overly broad exception catch

### 6. CONFIRMED — Dead dependency guard in expander

- **File:** `agent_actions/output/response/expander.py:406-413`
- **Summary:** Post-call check for missing 'dependencies' key is unreachable — _create_agent_from_action unconditionally sets it. Dead code providing false safety.
- **Severity:** LOW — dead code

---

## Recommended fix priority

| Priority | Findings | Effort |
|----------|----------|--------|
| P0 (wrong type) | #1 (FileWriteError never raised) | Small — fix operation name matching |
| P0 (silent fallback) | #2 (dispatch_task fallback) | Small — raise instead of warn |
| P1 (type confusion) | #3 (required list/bool) | Medium — handle JSON Schema required correctly |
| P1 (observability) | #4 (0 bytes) | Small — compute actual bytes |
| P2 (broad catch) | #5 (ConfigValidationError) | Small — narrow exception type |
| P3 | #6 (dead code) | Tiny — remove |
