# Code Review: agent_actions/models/

**Date:** 2026-06-17
**Reviewer:** Claude (single-angle deep review)
**Files reviewed:** 2 Python files + callers

---

## Findings

### 1. CONFIRMED — Wrong FieldSource on input fields in schema_service

- **File:** `agent_actions/workflow/schema_service.py:252,262`
- **Summary:** All input fields (required and optional) are tagged `FieldSource.TOOL_OUTPUT`. That enum member describes output provenance (produced by UDF tool), not input provenance. Renderer ignores `.source` on inputs today.
- **Failure scenario:** Future code branching on `input_field.source` gets TOOL_OUTPUT for every input field including LLM context-scope fields — produces incorrect formatting or dead-code paths.
- **Severity:** MEDIUM — wrong data, silent today

### 2. CONFIRMED — FieldInfo.to_dict() asymmetric key rename breaks round-trip

- **File:** `agent_actions/models/action_schema.py:32`
- **Summary:** Python attribute is `field_type` but to_dict() serializes as `"type"`. No round-trip possible — `FieldInfo(**d)` fails or uses default.
- **Severity:** MEDIUM — serialization contract violation

### 3. CONFIRMED — ActionKind.SEED is dead in runtime pipeline

- **File:** `agent_actions/models/action_schema.py:44`
- **Summary:** No DataFlowNode is ever assigned `agent_kind=SEED`. A SEED-kinded ActionSchema in schema_renderer falls through all branches silently with no label.
- **Severity:** LOW — dead enum member

### 4. CONFIRMED — ActionKind re-export shim with noqa suppression

- **File:** `agent_actions/models/action_schema.py:9`
- **Summary:** ActionKind imported from config/schema.py with `noqa: F401`. Move or rename in config/schema.py causes silently suppressed ImportError.
- **Severity:** LOW — fragile re-export

### 5. CONFIRMED — to_dict() redundantly recomputes derived properties

- **File:** `agent_actions/models/action_schema.py:56`
- **Summary:** available_outputs, dropped_outputs, required_inputs, optional_inputs are computed properties already derivable from output_fields/input_fields, but to_dict() also embeds them — double iteration, redundant keys.
- **Severity:** LOW — unnecessary overhead

### 6. CONFIRMED — Test docstring says "4 members" but enum has 5

- **File:** `tests/unit/models/test_action_schema.py:16`
- **Summary:** Stale docstring. Assertion is correct (== 5) but docstring contradicts.
- **Severity:** LOW — stale docs

---

## Recommended fix priority

| Priority | Findings | Effort |
|----------|----------|--------|
| P1 | #1 (wrong FieldSource), #2 (key rename) | Small — fix source assignment, fix key name |
| P2 | #3 (dead SEED), #4 (re-export shim) | Small — remove or document |
| P3 | #5, #6 (overhead, stale docs) | Tiny |
