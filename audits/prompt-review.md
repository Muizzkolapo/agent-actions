# Code Review: agent_actions/prompt/

**Date:** 2026-06-17
**Reviewer:** Claude (single-angle deep review)
**Files reviewed:** 18 Python files

---

## Findings

### 1. CONFIRMED — Silent fallback: null prompt resolves to generic "Process the following content"

- **File:** `agent_actions/prompt/formatter.py:51`
- **Summary:** `prompt: null` in YAML config bypasses empty-string guard (requires isinstance str), bypasses key-missing guard (key IS present), hits `if not raw_prompt` and silently returns generic prompt. LLM action runs with nonsense prompt.
- **Severity:** HIGH — silent wrong behavior, no error

### 2. CONFIRMED — Token limit guard bypassed for most providers

- **File:** `agent_actions/prompt/message_builder.py:338`
- **Summary:** Groq, Cohere, Gemini, and all non-json-mode paths omit `model_name=` from `MessageBuilder.build()`. Guard `if model_name is not None` never fires. Oversized prompts sent to provider without PromptTooLargeError preflight.
- **Failure scenario:** 40k token prompt on mixtral-8x7b-32768 → sent without check → provider returns API error after network round-trip.
- **Severity:** MEDIUM — missing preflight validation

### 3. CONFIRMED — Skipped-dep re-render not guarded against second UndefinedError

- **File:** `agent_actions/prompt/service.py:371`
- **Summary:** After injecting _PermissiveNamespace for first missing dep, re-render happens outside inner except block. Second missing dep raises UndefinedError → surfaces as TemplateVariableError blaming user's template.
- **Severity:** MEDIUM — misleading error message

### 4. CONFIRMED — Seed namespace silently overwrites action named 'seed'

- **File:** `agent_actions/prompt/context/scope_application.py:149`
- **Summary:** Warning logged but overwrite proceeds. Upstream action named 'seed' loses its output namespace. LLM receives static seed data where computed output was expected.
- **Severity:** MEDIUM — data corruption on namespace collision

### 5. CONFIRMED — Dead code: _enrich_source_namespace

- **File:** `agent_actions/prompt/context/scope_namespace.py:56`
- **Summary:** Defined and tested but never called from production. Source namespace enrichment logic missing at runtime.
- **Severity:** LOW — dead code with false test coverage

### 6. CONFIRMED — Dead code: replace_field_references and helpers

- **File:** `agent_actions/prompt/prompt_utils.py:207`
- **Summary:** Entire bare-brace field substitution system ({source.field} syntax) unreachable from production. Tests pass but feature doesn't work end-to-end.
- **Severity:** LOW — dead code, misleading tests

---

## Recommended fix priority

| Priority | Findings | Effort |
|----------|----------|--------|
| P0 (silent wrong behavior) | #1 (null prompt fallback) | Small — raise on None prompt |
| P1 (missing validation) | #2 (token guard bypass) | Medium — pass model_name from all providers |
| P1 (misleading error) | #3 (skipped-dep re-render) | Small — wrap re-render in try/except |
| P2 (namespace collision) | #4 (seed overwrite) | Small — raise instead of warn+overwrite |
| P3 (dead code) | #5, #6 | Small — remove |
