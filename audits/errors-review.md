# Code Review: agent_actions/errors/

**Date:** 2026-06-17
**Reviewer:** Claude (single-angle deep review)
**Files reviewed:** 11 Python files

---

## Findings

### 1. CONFIRMED — Three dead exception classes never raised in production

- **Files:** `processing.py:30` (SerializationError), `external_services.py:63` (LLMResponseParseError), `common.py:7` (InvalidParameterError)
- **Summary:** All three are defined, exported, but never raised anywhere in production code. LLMResponseParseError is the most dangerous — its name implies it signals JSON parse failures, but the pipeline uses `_parse_error` dict markers instead.
- **Failure scenario:** A caller catches `LLMResponseParseError` expecting it to fire on LLM parse failures. It never does. The guard silently does nothing.
- **Severity:** MEDIUM — false API surface, misleading contracts

### 2. CONFIRMED — Falsy coercion collapses empty list to None in ContextStructureError

- **File:** `agent_actions/errors/preflight.py:187`
- **Summary:** `actual_fields if actual_fields else None` collapses `[]` (known-empty context) to None (unknown context). User cannot distinguish "no fields loaded" from "fields unknown".
- **Fix:** `actual_fields if actual_fields is not None else None`
- **Severity:** MEDIUM — loses diagnostic information in error messages

### 3. CONFIRMED — ConfigValidationError parameter name misleads callers

- **File:** `agent_actions/errors/configuration.py:12`
- **Summary:** First positional arg is named `message` but at 15+ call sites it's used as `config_key`. When `reason` is also provided, `message` doubles as a key — producing `'Configuration validation failed for "your_full_sentence": reason'`.
- **Severity:** LOW — confusing API, latent bug for new callers

### 4. CONFIRMED — Private cross-module import of _render_sections

- **File:** `agent_actions/errors/validation.py:6`
- **Summary:** `SchemaValidationError` imports `_render_sections` directly from `preflight.py` — an underscore-prefixed internal function with no export or stability guarantee.
- **Severity:** LOW — fragile coupling

---

## Recommended fix priority

| Priority | Findings | Effort |
|----------|----------|--------|
| P1 | #2 (falsy coercion) | Tiny — change condition |
| P2 | #1 (dead exceptions) | Small — remove or wire up |
| P3 | #3, #4 (naming, coupling) | Small cleanup |
