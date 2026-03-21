# Fallback Pattern Audit

**Date:** 2026-03-21
**Scope:** `agent_actions/` — all 410 Python files
**Goal:** Identify fallback patterns and classify as valid, questionable, or needs-fix

---

## Executive Summary

**Total fallback instances found:** ~300+
**Valid (defensive, intentional):** ~295
**Needs attention:** 5 specific locations

The codebase is generally disciplined — most fallbacks are idiomatic Python with appropriate logging. The problematic patterns fall into two categories:

1. **Silent fallbacks** that don't signal to downstream code that degradation occurred
2. **Broad exception catches** that could mask unexpected errors

---

## NEEDS FIX — Silent Fallbacks That Mask Problems

### 1. `schema_extractor.py:277-280` — Silent schema loader failure

**File:** `agent_actions/validation/static_analyzer/schema_extractor.py`
**Lines:** 277-280

```python
except Exception as e:
    logger.debug(
        "Schema loading failed for '%s': %s", schema_name, e, exc_info=True
    )
```

**Problem:** Catches broad `Exception`, logs at debug (invisible in normal operation), and continues without marking `output.is_dynamic = True` or any other state change. Downstream code has no way to know the schema was not actually loaded — it just sees empty fields.

**Recommendation:** Either:
- Log at `warning` level so operators notice
- Set `output.is_dynamic = True` to signal the schema couldn't be resolved
- Narrow the except clause to specific expected exceptions

---

### 2. `schema_extractor.py:307-310` — Second silent schema fallback

**File:** `agent_actions/validation/static_analyzer/schema_extractor.py`
**Lines:** 307-310

Same pattern as #1. The function has two fallback layers for schema loading and both silently degrade.

**Recommendation:** Same as #1. At minimum, after both loaders fail, explicitly mark the output as unresolved.

---

### 3. `generator.py:72` — Silent `pass` on FileNotFoundError

**File:** `agent_actions/tooling/docs/generator.py`
**Line:** ~72

```python
except FileNotFoundError:
    pass  # Schema file not found, skip
```

**Problem:** When a schema file referenced in config doesn't exist, this silently skips it. The generated docs will have missing output field information with no indication that something went wrong. This is the classic "quick fix fallback" — it prevents a crash but hides a configuration error.

**Recommendation:**
- Log at `warning` level: `"Schema file '%s' referenced in config not found, outputs will be incomplete"`
- Consider adding the missing schema to a warnings list in the generated output

---

### 4. `workflow_static_analyzer.py:363-366` — Broad `Exception` catch for dependency inference

**File:** `agent_actions/validation/static_analyzer/workflow_static_analyzer.py`
**Lines:** 363-366

```python
except Exception as e:
    logger.debug("Dependency inference failed for '%s': %s", name, e, exc_info=True)
    deps_list = action_config.get("depends_on") or action_config.get("dependencies", [])
```

**Problem:** The fallback to explicit `depends_on` is reasonable, but the broad `Exception` catch means bugs in `infer_dependencies()` (e.g., TypeError from bad data, KeyError from schema changes) are silently swallowed and downgraded to config-based resolution. This could mask real bugs in the inference logic.

**Recommendation:**
- Narrow to expected exceptions (e.g., `KeyError`, `ValueError`, specific custom exceptions)
- Log at `warning` when falling back, so it's visible during normal validation runs
- The fallback behavior itself is valid — just tighten what triggers it

---

### 5. `data_scanners.py` — Broad `Exception` catch for SQLite scanning

**File:** `agent_actions/tooling/docs/scanner/data_scanners.py`

```python
except Exception as e:
    logger.debug("Failed to scan workflow DB %s: %s", db_file, e, exc_info=True)
```

**Problem:** SQLite scanning catches all exceptions at debug level. A corrupted DB, permission error, or schema mismatch would all be silently ignored. While this is acceptable for a non-critical docs scanner, it makes debugging difficult when the docs generator produces incomplete output.

**Recommendation:** Log at `warning` level instead of `debug` for non-trivial exceptions (e.g., anything other than `FileNotFoundError`).

---

## VALID — Properly Implemented Fallback Patterns

These are all intentional, well-logged, and follow established project patterns:

### Token count extraction (`or 0` patterns)
**Files:** All LLM provider clients (cohere, gemini, ollama, mistral, openai)
**Pattern:** `getattr(response, "prompt_tokens", None) or 0`
**Why valid:** LLM SDKs have inconsistent response shapes. Defaulting to 0 for missing token counts is safe — it's metadata, not business logic.

### Dict access with defaults (`.get()` patterns)
**Files:** Throughout codebase (150+ instances)
**Pattern:** `config.get("key", [])`, `data.get("field", {})`
**Why valid:** Idiomatic Python for optional config/data fields. Standard defensive coding.

### Constructor parameter guards (`or []`, `or {}`)
**Files:** `errors/preflight.py`, `errors/validation.py`, `processing/types.py`
**Pattern:** `field_order or []`, `data or []`
**Why valid:** Guards against `None` being passed for list/dict parameters. Prevents downstream TypeErrors.

### Batch scanning loops (continue on error)
**Files:** `tooling/docs/scanner/code_scanners.py`, `data_scanners.py`, `__init__.py`
**Pattern:** Catch specific exceptions (SyntaxError, UnicodeDecodeError, OSError), log, continue
**Why valid:** Scanning operations should be resilient to individual file failures. Exceptions are specific and logged.

### CLI error handling cascade
**Files:** `cli/cli_decorators.py`, `cli/run.py`
**Pattern:** Known errors → pretty-print, unknown errors → re-raise with traceback
**Why valid:** Proper error classification at the CLI boundary. Finally blocks protect against cleanup failures masking original errors.

### Path validation wrapping
**File:** `config/project_paths.py`
**Pattern:** Wrap unexpected exceptions in ValidationError with context
**Why valid:** Exception enrichment at module boundary. Known errors pass through, unknown get wrapped with debugging context.

### Error wrapper status code extraction
**File:** `llm/providers/error_wrapper.py`
**Pattern:** Cascading `getattr` for status codes across different SDK shapes
**Why valid:** Vendor-agnostic error classification. Different providers store status codes in different places.

### Response validator fallback message
**File:** `processing/recovery/response_validator.py`
**Pattern:** `report.validation_errors or ["Schema mismatch detected"]`
**Why valid:** Prevents confusing empty error feedback. The fallback message is informative.

### Prompt validator early returns
**File:** `validation/prompt_validator.py`
**Pattern:** `if not X: return 0`
**Why valid:** These are validation guards, not fallbacks. Early returns on invalid preconditions is standard validation pattern.

### Config manager list access
**File:** `config/manager.py`
**Pattern:** `self.user_config.get("actions") or []`
**Why valid:** Standard safe iteration over optional config field.

### LSP indexer tool_path resolution
**File:** `tooling/lsp/indexer.py`
**Pattern:** Try loading from config, fallback to `["tools"]`
**Why valid:** Sensible default when config is absent. Specific exceptions caught. Logged at debug.

### Result collector data guards
**File:** `processing/result_collector.py`
**Pattern:** `result.data or []`
**Why valid:** Guards against None data for safe iteration. Consistent across all status branches.

### Batch reconciliation count chain
**File:** `llm/batch/services/shared.py`
**Pattern:** `len(expected) or record_count or 0`
**Why valid:** Clear fallback chain for count computation. Each level is a reasonable alternative.

---

## Pattern Statistics

| Pattern Type | Count | Valid | Needs Attention |
|---|---|---|---|
| `or []` / `or {}` (null guards) | ~35 | 35 | 0 |
| `.get()` with defaults | ~150+ | 150+ | 0 |
| `getattr()` with defaults | ~50+ | 50+ | 0 |
| `or 0` (token counts) | ~30 | 30 | 0 |
| `except` with continue (scanning) | ~10 | 8 | 2 |
| `except` with fallback behavior | ~15 | 12 | 3 |
| `except: pass` / silent | ~2 | 0 | 2 |
| Conditional early returns | ~20+ | 20+ | 0 |

---

## Action Items

| Priority | File | Issue | Fix |
|---|---|---|---|
| P2 | `schema_extractor.py:277-280` | Silent broad exception, no state change | Narrow exception + set `is_dynamic=True` |
| P2 | `schema_extractor.py:307-310` | Same as above (second loader) | Same fix |
| P3 | `generator.py:~72` | Silent `pass` on missing schema | Log at warning level |
| P3 | `workflow_static_analyzer.py:363-366` | Broad exception hides inference bugs | Narrow to expected exceptions |
| P3 | `data_scanners.py` | Broad exception on SQLite scan | Log at warning for non-trivial errors |
