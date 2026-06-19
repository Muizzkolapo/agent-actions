# Code Review: agent_actions/input/

**Date:** 2026-06-17
**Reviewer:** Claude (single-angle deep review)
**Files reviewed:** 44 Python files

---

## Findings

### 1. CONFIRMED — Silent empty-list return on transform error drops records

- **File:** `agent_actions/input/preprocessing/processing/data_processor.py:55`
- **Summary:** process_item catches ValueError/TypeError/KeyError, calls handle_processing_error (debug/info only), returns []. Records vanish from pipeline output with no user-visible signal.
- **Severity:** HIGH — silent data loss

### 2. CONFIRMED — TruncateStrategy.handle_chunking_error silently drops records like SkipStrategy

- **File:** `agent_actions/input/preprocessing/chunking/strategies/fallback_strategies.py:83`
- **Summary:** Class named "Truncate" but handle_chunking_error returns [] — identical to SkipStrategy. Users configuring `fallback_strategy: truncate` lose records silently.
- **Severity:** HIGH — misdocumented behavior causes data loss

### 3. CONFIRMED — _should_save_source_items compares only first record's field count

- **File:** `agent_actions/input/preprocessing/staging/initial_pipeline.py:278`
- **Summary:** Uses new_items[0] vs existing_items[0] for field count comparison. Heterogeneous data where record 0 is atypical causes permanent stale source data.
- **Severity:** MEDIUM — stale data persisted across runs

### 4. CONFIRMED — Empty CSV returns empty list with no warning

- **File:** `agent_actions/input/loaders/tabular.py:40`
- **Summary:** Header-only or zero-byte CSV → empty list → pipeline proceeds with 0 records → no warning, no error. User gets silent no-op run.
- **Severity:** MEDIUM — silent no-op

### 5. CONFIRMED — Global sys.modules UDF dedup causes stale UDF injection

- **File:** `agent_actions/input/loaders/udf.py:60`
- **Summary:** UDF with same module name from different project directories gets skipped if already in sys.modules. Second project silently inherits first project's UDF.
- **Severity:** MEDIUM — cross-project state contamination

### 6. CONFIRMED — CSV batch path TOCTOU re-reads file from disk

- **File:** `agent_actions/input/preprocessing/staging/initial_pipeline.py:424`
- **Summary:** _prepare_batch_data re-reads file via TabularLoader after FileReader already read it. File modification between reads produces inconsistent pipeline state.
- **Severity:** LOW — race condition on file mutation

---

## Recommended fix priority

| Priority | Findings | Effort |
|----------|----------|--------|
| P0 (data loss) | #1 (transform error drops records), #2 (truncate = skip) | Small — raise or log warning, fix truncate behavior |
| P1 (stale data) | #3 (first-record comparison) | Small — compare all or representative sample |
| P1 (silent no-op) | #4 (empty CSV) | Small — warn on empty input |
| P2 (state leak) | #5 (UDF dedup) | Medium — scope to project root |
| P3 | #6 (TOCTOU) | Low priority |
