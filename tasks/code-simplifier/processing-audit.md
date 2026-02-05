# Code Simplification Audit: processing

**Audited path:** `agent_actions/processing/`
**Date:** 2026-02-05
**Modules reviewed:** 25 (14 top-level .py files, 5 invocation/*.py, 4 recovery/*.py, 1 transform file, 1 empty strategies dir)
**Total lines of code:** ~3,800 (top-level: 3,239 + invocation: ~600 + recovery: ~700)

---

## Executive Summary

The `processing` folder is the core record-processing engine, bridging input/preparation with LLM execution and output enrichment. The codebase has been through several refactoring phases (Phase 2: PreparedTask, Phase 3: InvocationStrategy, Phase 4: unified enrichment), which left behind **significant dead code in `processor.py`** (5 private methods, ~230 lines, no longer called after TaskPreparer extraction), a **completely orphaned `lineage_mixin.py`** (172 lines, zero consumers), an **entirely unused `ProcessingResultAdapter` class** (86 lines, no consumers outside its own module), a **dead `strategies/` subdirectory** (empty except `__pycache__`), and a **dead `transform/` subdirectory** (single-line `__init__.py`, no real content). The code that *is* active is generally well-structured, but there are notable duplication patterns in `online.py` (4 methods repeating the same `run_dynamic_agent` call setup), redundant `hasattr` guards on dataclass fields, and opportunity to consolidate the duplicated `_normalize_input` / `_prepare_source_snapshot` methods that exist in both `processor.py` and `task_preparer.py`.

**Estimated cleanup yield:** ~500-600 lines of dead code removal (P1), plus ~100-150 lines of deduplication (P2).

---

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

1. **Dead code: `processor.py` lines 438-636 -- 5 orphaned private methods**
   - **File:** `agent_actions/processing/processor.py`
   - **Lines:** 438-636 (methods `_normalize_input`, `_prepare_source_snapshot`, `_evaluate_guard`, `_get_source_content`, `_prepare_prompt`)
   - **What:** These 5 private methods are never called. After Phase 2 extracted preparation into `TaskPreparer`, the `process()` method (line 132) delegates to `task_preparer.prepare()` instead. Grep confirms zero calls to `self._normalize_input`, `self._evaluate_guard`, `self._get_source_content`, or `self._prepare_prompt` anywhere in the codebase.
   - **Why:** ~200 lines of dead code that duplicates logic now living in `task_preparer.py`. Creates maintenance confusion about which version is canonical.
   - **Risk:** Very low. These are private methods with no external callers. `self._transform_response` (line 637) and `self._create_item_context` (line 670) and `self._prepare_source_snapshot` (line 473) ARE still called -- only the five listed above are dead.
   - **Correction:** `_prepare_source_snapshot` IS still called at lines 412 and 461 within `process_batch`'s exception handler. However, the same logic exists in `task_preparer.py` lines 207-226. The methods `_normalize_input` (438-471), `_evaluate_guard` (494-558), `_get_source_content` (560-591), and `_prepare_prompt` (593-635) are fully dead.

2. **Dead module: `lineage_mixin.py` -- entirely orphaned (172 lines)**
   - **File:** `agent_actions/processing/lineage_mixin.py`
   - **Lines:** 1-172 (entire file)
   - **What:** `LineageTrackingMixin` is defined but never imported or used anywhere in the codebase. Grep for `LineageTrackingMixin` returns only the definition line. Additionally, the mixin calls `self._get_processor_idx()` (line 170) which is not defined in the mixin itself and has no definition anywhere in the codebase.
   - **Why:** 172 lines of dead code. The lineage functionality has been replaced by `LineageEnricher` in `enrichment.py` (lines 34-107).
   - **Risk:** None. Zero consumers. Can be deleted outright.

3. **Dead module: `ProcessingResultAdapter` in `result_adapters.py` -- no external consumers (86 lines)**
   - **File:** `agent_actions/processing/result_adapters.py`
   - **Lines:** 1-86 (entire file)
   - **What:** `ProcessingResultAdapter` is exported in `__init__.py` but has zero actual consumers outside the processing package. Grep shows it is only referenced in: (a) its own module docstring examples (lines 7, 10, 13), (b) its class definition (line 21), and (c) `__init__.py` re-export (lines 27, 74). No other module imports or uses it.
   - **Why:** 86 lines of unused backward-compatibility adapter code. The `ResultCollector` has superseded this pattern.
   - **Risk:** Low. Exported in `__all__` so theoretically part of public API, but with zero consumers. Check with team before removing.

4. **Dead directory: `strategies/` -- empty (only `__pycache__`)**
   - **File:** `agent_actions/processing/strategies/`
   - **What:** The directory contains only a `__pycache__/` folder with stale `.pyc` files (for `__init__.py`, `base.py`, `online.py`, `batch.py`). All Python source files have been deleted, but the `__pycache__` and directory remain.
   - **Why:** Stale remnant from a previous refactoring (likely before the `invocation/` package was created). Creates confusion in the codebase structure.
   - **Risk:** None. Delete directory entirely.

5. **Dead directory: `transform/` -- effectively empty**
   - **File:** `agent_actions/processing/transform/`
   - **What:** Contains only `__init__.py` with content `"""Package."""` (1 line) and a `_MANIFEST.md` confirming it only exists "for exports between processors" but has no actual exports. The `_MANIFEST.md` itself says "Only `__init__.py` exists."
   - **Why:** Empty shell with no purpose. No imports from `agent_actions.processing.transform` exist anywhere.
   - **Risk:** None. Delete directory entirely.

6. **Redundant `import logging` inside `process_batch` method**
   - **File:** `agent_actions/processing/processor.py`
   - **Lines:** 399-401
   - **What:** `import logging` and `logging.getLogger(__name__).error(...)` appear inside the exception handler at line 399, despite `logging` already being imported at line 3 and `logger` already defined at line 30.
   - **Why:** Redundant import inside a function body. Should use the module-level `logger` instead.
   - **Risk:** None.

7. **Dead `_normalize_input` in `processor.py` duplicates `task_preparer.py`**
   - **File:** `agent_actions/processing/processor.py` lines 438-471 vs. `agent_actions/processing/task_preparer.py` lines 168-205
   - **What:** Nearly identical `_normalize_input` methods in both files. The `processor.py` version is dead (uncalled). The `task_preparer.py` version is the active one.
   - **Why:** Phase 2 refactoring extracted this logic but left the old copy. Removing the dead copy eliminates confusion about which is canonical.
   - **Risk:** None (removing dead code).

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

8. **Code duplication: `online.py` -- 4 methods repeat identical `run_dynamic_agent` call setup**
   - **File:** `agent_actions/processing/invocation/online.py`
   - **Lines:** 124-355 (methods `_invoke_direct`, `_invoke_with_retry`, `_invoke_with_reprompt`, `_invoke_with_retry_and_reprompt`)
   - **What:** All four methods perform the same pattern: (a) import `run_dynamic_agent` from helpers, (b) extract `tools_path` from `context.agent_config.get("tools", {}).get("path")`, (c) call `run_dynamic_agent` with the same 7 arguments. The duplication is especially pronounced -- lines 139-151, 172-185, 240-253, 294-310 are near-identical.
   - **Why:** Each method imports `run_dynamic_agent` independently (4 times), resolves `tools_path` independently (4 times at lines 141, 174, 242, 296), and constructs the same argument list. This could be extracted into a single `_build_llm_callable(task, context) -> Callable` factory method.
   - **Risk:** Low. Internal private methods. Would reduce ~80 lines of duplication.

9. **Duplicated retry metadata tracking in `online.py`**
   - **File:** `agent_actions/processing/invocation/online.py`
   - **Lines:** 193-202 and 318-327
   - **What:** The retry metadata construction code (`RetryMetadata(attempts=..., failures=..., ...)`) is duplicated between `_invoke_with_retry` (lines 193-202) and `_invoke_with_retry_and_reprompt` (lines 318-327). Both blocks are character-for-character identical.
   - **Why:** Extract into a shared `_track_retry_metadata(retry_result, recovery_metadata)` helper method.
   - **Risk:** Low.

10. **Redundant `hasattr(context, "record_index")` checks in `processor.py`**
    - **File:** `agent_actions/processing/processor.py`
    - **Lines:** 183, 198, 538, 549
    - **What:** Four instances of `context.record_index if hasattr(context, "record_index") else 0`. Since `context` is always `ProcessingContext` (a dataclass with `record_index: int = 0` at line 256 of `types.py`), `hasattr` will always return `True`. The guard is unnecessary.
    - **Why:** Defensive code from before the type was a proper dataclass. Adds noise and suggests the field might be absent when it cannot be.
    - **Risk:** Very low. `ProcessingContext` always has `record_index`.

11. **`error_handling.py` -- 3 methods likely have zero callers**
    - **File:** `agent_actions/processing/error_handling.py`
    - **Lines:** 262-301 (`with_fallback`), 303-343 (`handle_partial_failure`), 345-401 (`create_error_recovery_state`, `_get_recovery_instructions`)
    - **What:** `with_fallback` (decorator factory), `handle_partial_failure`, and `create_error_recovery_state` are defined in the mixin but grep shows zero callers outside the mixin itself. They appear to be anticipatory code that was never integrated.
    - **Why:** ~140 lines of potentially dead code. However, since this is a mixin inherited by 4 external classes (`FileWriter`, `BaseLoader`, `FileReader`, `DataProcessor`), they could theoretically be called on those instances. Need runtime or broader grep verification.
    - **Risk:** Medium. Mixin methods are available on subclasses, so removing them requires checking all subclass usage patterns. Recommend marking as `@deprecated` first.

12. **`error_handling.py` uses deprecated `datetime.utcnow()`**
    - **File:** `agent_actions/processing/error_handling.py`
    - **Lines:** 61, 360
    - **What:** `datetime.utcnow()` is deprecated since Python 3.12 in favor of `datetime.now(timezone.utc)`. The rest of the codebase (e.g., `processor.py` line 342, `online.py` lines 201, 326) correctly uses `datetime.now(timezone.utc)`.
    - **Why:** Inconsistency within the processing package. `utcnow()` returns a naive datetime without timezone info.
    - **Risk:** Very low.

13. **`recovery/stats.py` -- all public functions may be unused (220 lines)**
    - **File:** `agent_actions/processing/recovery/stats.py`
    - **Lines:** 1-220 (entire file)
    - **What:** `RecoveryStats`, `calculate_recovery_stats_from_results`, `calculate_recovery_stats_from_output_data`, `add_recovery_stats_to_manifest`, `add_recovery_stats_to_agent_status` are defined but grep shows zero callers outside the file itself (all grep hits are definition lines, docstring examples, or commented-out integration guide code at lines 197-219).
    - **Why:** 220 lines of infrastructure code with zero integration points. The integration guide at the bottom is still commented out.
    - **Risk:** Medium. This may be intentionally waiting for integration. But if it has been sitting unused for multiple releases, it is dead weight.

14. **`recovery/retry.py` -- `execute_with_fallback` method has zero callers**
    - **File:** `agent_actions/processing/recovery/retry.py`
    - **Lines:** 209-234
    - **What:** `RetryService.execute_with_fallback()` is defined but grep shows zero callers. All actual usage goes through `execute()` directly.
    - **Why:** ~25 lines of unused convenience method.
    - **Risk:** Low.

15. **`processor_init.py` -- thin wrapper with stale comments**
    - **File:** `agent_actions/processing/processor_init.py`
    - **Lines:** 1-14 (entire file)
    - **What:** This 14-line file only re-exports `ProcessorErrorHandlerMixin` from `error_handling.py`. Its docstring says "Processor infrastructure and helpers" but it imports nothing related to initialization. The commented-out lines (7, 11-12) reference `run_dynamic_agent` and `transform_with_passthrough` but those are not exported.
    - **Why:** Confusing module name (`processor_init.py` suggests initialization logic). Only purpose is a single re-export that could live directly in `__init__.py`.
    - **Risk:** Low. Downstream imports use `from agent_actions.processing.error_handling import ProcessorErrorHandlerMixin` directly (not through `processor_init.py`).

16. **`result_collector.py` -- long method with repetitive status branching**
    - **File:** `agent_actions/processing/result_collector.py`
    - **Lines:** 23-202 (single `collect_results` method: 180 lines)
    - **What:** The `collect_results` static method is 180 lines with a large `if/elif/elif/elif/elif/else` chain (lines 94-188) handling each `ProcessingStatus` variant. Each branch follows the same pattern: increment counter, maybe extend output, log, fire event. This is a classic case for a dispatch table or strategy mapping.
    - **Why:** Hard to maintain when adding new status types. Each branch is 10-20 lines of similar boilerplate.
    - **Risk:** Low-medium. The method has good test coverage via integration tests.

17. **Duplicate `_prepare_source_snapshot` in `processor.py` and `task_preparer.py`**
    - **File:** `agent_actions/processing/processor.py` lines 473-492 and `agent_actions/processing/task_preparer.py` lines 207-226
    - **What:** Identical method logic in both files: checks for `chunk_info` in dict, excludes `target_id/record_index/chunk_index` keys, copies dict or returns item as-is. The `processor.py` version IS still called (in `process_batch` exception handler at line 412).
    - **Why:** Should be consolidated into a single shared utility function.
    - **Risk:** Low. Straightforward extraction.

### P3 -- Low Impact (Nice-to-have, minor cleanups)

18. **f-string logging in `reprompt.py` (inconsistent with rest of codebase)**
    - **File:** `agent_actions/processing/recovery/reprompt.py`
    - **Lines:** 126, 146, 153, 165, 179
    - **What:** Uses `logger.info(f"[{context}] ...")` f-string interpolation for log messages. The rest of the processing package uses `logger.info("...", arg1, arg2)` lazy formatting (e.g., `processor.py` line 401, `retry.py` lines 163-170).
    - **Why:** f-string logging defeats lazy evaluation and is inconsistent. Not a correctness issue but a style inconsistency.
    - **Risk:** None.

19. **`enrichment.py` line 223 -- mutable default argument `enrichers: List[Enricher] = None`**
    - **File:** `agent_actions/processing/enrichment.py`
    - **Line:** 223
    - **What:** The signature `def __init__(self, enrichers: List[Enricher] = None)` uses `None` as default (correct) but the type annotation `List[Enricher]` does not include `Optional`. Should be `Optional[List[Enricher]] = None`.
    - **Why:** Type annotation is technically incorrect -- `None` is not `List[Enricher]`.
    - **Risk:** None. Cosmetic type hint fix.

20. **`enrichment.py` -- `datetime` import inside method body**
    - **File:** `agent_actions/processing/enrichment.py`
    - **Lines:** 255-256
    - **What:** `from datetime import datetime` is imported inside `EnrichmentPipeline.enrich()`. This is a standard library module that could be at the top level.
    - **Why:** Minor inconsistency. Other modules in the package import datetime at the top.
    - **Risk:** None.

21. **`exhausted_builder.py` -- duplicate `target_id` check**
    - **File:** `agent_actions/processing/exhausted_builder.py`
    - **Lines:** 67-72
    - **What:** Lines 67-68 check `if original_row.get("target_id")` and set `exhausted_item["target_id"]`. Lines 71-72 check `if original_row.get("target_id")` again for `parent_target_id`. The second check is always true if the first was, since they test the same condition on the same data.
    - **Why:** The two blocks could be merged under a single `target_id` check to avoid redundant dictionary lookups.
    - **Risk:** None.

22. **`types.py` -- `to_dict()` methods could use `dataclasses.asdict()`**
    - **File:** `agent_actions/processing/types.py`
    - **Lines:** 57-67 (`RetryMetadata.to_dict`), 85-91 (`RepromptMetadata.to_dict`), 106-113 (`RecoveryMetadata.to_dict`)
    - **What:** Three `to_dict()` methods manually construct dictionaries from dataclass fields. `dataclasses.asdict()` could do this automatically, with filtering for optional fields.
    - **Why:** Minor boilerplate reduction. However, the current approach gives explicit control over None-field omission (e.g., `RetryMetadata.to_dict` conditionally includes `timestamp`), which `asdict()` would not do by default.
    - **Risk:** Low. The manual approach is fine; this is a style preference.

23. **`processor.py` -- `import logging` at line 399 inside except block**
    - **File:** `agent_actions/processing/processor.py`
    - **Lines:** 399-401
    - **What:** Redundant `import logging` followed by `logging.getLogger(__name__).error(...)` inside exception handler. Module already has `import logging` at line 3 and `logger = logging.getLogger(__name__)` at line 30.
    - **Why:** Should simply use `logger.error(...)` on the existing module-level logger.
    - **Risk:** None.

24. **`processor.py` line 341 -- `from datetime import datetime, timezone` inside method**
    - **File:** `agent_actions/processing/processor.py`
    - **Lines:** 340-341
    - **What:** `from datetime import datetime, timezone` imported inside `process_batch()` method. Could be a top-level import.
    - **Why:** Minor style inconsistency. Lazy import is not necessary here (no circular dependency risk with `datetime`).
    - **Risk:** None.

25. **`prepared_task.py` -- `PreparationContext` has 15 fields, mirrors `ProcessingContext` closely**
    - **File:** `agent_actions/processing/prepared_task.py`
    - **Lines:** 88-175
    - **What:** `PreparationContext` has 14 fields that substantially overlap with `ProcessingContext` (13 of 14 fields are shared). The `from_processing_context` classmethod (lines 146-175) manually copies every field. This is a maintenance risk -- any new field added to `ProcessingContext` must also be added to `PreparationContext`.
    - **Why:** Consider whether `PreparationContext` could simply accept a `ProcessingContext` reference instead of copying all fields. Or use a shared base class.
    - **Risk:** Medium for refactoring (many consumers), low for the current state.

26. **`error_handling.py` -- exclamation marks in comments**
    - **File:** `agent_actions/processing/error_handling.py`
    - **Lines:** 25, 167, 193, 225
    - **What:** Comments like `# New modular pattern!` appear 4 times. These are celebratory annotations that should have been cleaned up after the migration was complete.
    - **Why:** Noise in comments. Not descriptive of *why*, just *what*.
    - **Risk:** None.

---

## Module-by-Module Breakdown

### `__init__.py`
- **Lines:** 75
- **Complexity:** Low (pure re-export module)
- **Findings:**
  - Exports `ProcessingResultAdapter` which has zero external consumers (P1-3)
  - Well-organized with `__all__` and section comments

### `types.py`
- **Lines:** 271
- **Complexity:** Low (pure data definitions)
- **Findings:**
  - P3-22: Manual `to_dict()` methods could potentially use `asdict()` (minor)
  - Good use of factory classmethods on `ProcessingResult`
  - `ProcessingContext.action_name` property (line 268) provides a useful accessor

### `processor.py`
- **Lines:** 699
- **Complexity:** Medium-high (main orchestrator, 699 lines)
- **Findings:**
  - **P1-1:** ~200 lines of dead private methods (lines 438-636)
  - **P1-6:** Redundant `import logging` at line 399
  - **P2-10:** 4 redundant `hasattr(context, "record_index")` guards
  - **P2-17:** Duplicate `_prepare_source_snapshot` (also in task_preparer.py)
  - **P3-23:** Redundant `import logging` in exception handler
  - **P3-24:** `datetime` imported inside method body
  - `process()` method (lines 132-322) is 190 lines -- reasonable for its orchestration role
  - `process_batch()` method (lines 324-434) is 110 lines -- could be simplified

### `processor_init.py`
- **Lines:** 14
- **Complexity:** Negligible
- **Findings:**
  - **P2-15:** Module is a thin re-export wrapper with stale commented-out code. Could be eliminated entirely.

### `task_preparer.py`
- **Lines:** 407
- **Complexity:** Medium (unified preparation pipeline)
- **Findings:**
  - **P2-17:** `_prepare_source_snapshot` duplicated from `processor.py`
  - Singleton pattern (`get_task_preparer`/`reset_task_preparer`) is appropriate for this use case
  - Well-structured with clear step comments
  - Multiple lazy imports (lines 185, 252, 289, 337, 369, 387) -- necessary to avoid circular imports

### `prepared_task.py`
- **Lines:** 180
- **Complexity:** Low (dataclasses and factory)
- **Findings:**
  - **P3-25:** `PreparationContext` closely mirrors `ProcessingContext` (15 overlapping fields)
  - Clean dataclass design with useful properties (`should_execute`, `is_passthrough`, `is_filtered`)

### `enrichment.py`
- **Lines:** 295
- **Complexity:** Medium (pipeline pattern with 6 enrichers + orchestrator)
- **Findings:**
  - **P3-19:** `Optional[List[Enricher]]` type hint missing on `__init__` parameter
  - **P3-20:** `datetime` imported inside method body
  - Good pipeline pattern with proper event tracking
  - Each enricher is concise and single-responsibility

### `error_handling.py`
- **Lines:** 401
- **Complexity:** Medium (mixin with 10+ methods)
- **Findings:**
  - **P2-11:** 3 methods (`with_fallback`, `handle_partial_failure`, `create_error_recovery_state`) likely have zero callers (~140 lines)
  - **P2-12:** Uses deprecated `datetime.utcnow()` at lines 61 and 360
  - **P3-26:** Stale `# New modular pattern!` comments (4 occurrences)
  - `handle_processing_error` (lines 74-146) is well-structured with format-specific error dispatch

### `helpers.py`
- **Lines:** 279
- **Complexity:** Medium (utility functions with schema validation)
- **Findings:**
  - `evaluate_guard_condition` (lines 16-40) delegates to `get_guard_evaluator()` -- thin wrapper
  - `run_dynamic_agent` (lines 43-129) is the central LLM execution entry point
  - `_validate_llm_output_schema` (lines 132-216) handles both strict and lenient modes
  - `transform_with_passthrough` (lines 247-279) is a thin wrapper around `PassthroughTransformer`
  - Three private guard helpers (lines 219-244) could potentially be inlined

### `exhausted_builder.py`
- **Lines:** 86
- **Complexity:** Low
- **Findings:**
  - **P3-21:** Duplicate `target_id` check (lines 67-72)
  - Clear single-responsibility: builds exhausted records with proper lineage

### `lineage_mixin.py`
- **Lines:** 172
- **Complexity:** Medium
- **Findings:**
  - **P1-2:** Entirely orphaned -- zero consumers anywhere in the codebase
  - References undefined `self._get_processor_idx()` at line 170 -- would crash if used
  - Superseded by `LineageEnricher` in `enrichment.py`

### `batch_context_adapter.py`
- **Lines:** 72
- **Complexity:** Low (two static factory methods)
- **Findings:**
  - Clean, focused adapter
  - Actively used by `llm/batch/processing/result_processor.py`
  - No issues found

### `result_adapters.py`
- **Lines:** 86
- **Complexity:** Low
- **Findings:**
  - **P1-3:** Zero external consumers -- only referenced in own docstring and `__init__.py` re-export
  - Clean code, but unused

### `result_collector.py`
- **Lines:** 202
- **Complexity:** Medium
- **Findings:**
  - **P2-16:** Single method `collect_results` is 180 lines with repetitive status branching
  - Proper event firing for each status, but boilerplate-heavy

### `invocation/__init__.py`
- **Lines:** 28
- **Complexity:** Low (re-exports)
- **Findings:** None. Clean package init.

### `invocation/strategy.py`
- **Lines:** 83
- **Complexity:** Low (ABC + Protocol)
- **Findings:** None. Clean interface definitions.

### `invocation/result.py`
- **Lines:** 128
- **Complexity:** Low (dataclass with factory methods)
- **Findings:** None. Well-designed with `immediate`, `queued`, `skipped`, `filtered` factories.

### `invocation/online.py`
- **Lines:** 356
- **Complexity:** Medium-high (4 execution paths with recovery combinations)
- **Findings:**
  - **P2-8:** 4 methods repeat identical `run_dynamic_agent` call setup (~80 lines duplicated)
  - **P2-9:** Retry metadata construction duplicated at lines 193-202 and 318-327
  - Method count is appropriate (each combines different recovery services)

### `invocation/batch.py`
- **Lines:** 249
- **Complexity:** Medium
- **Findings:**
  - `get_prepared_tasks()` (lines 222-238) constructs the same dict format as `flush()` (lines 171-177) -- minor duplication
  - Otherwise clean with proper lifecycle management (queue -> flush -> cleanup)

### `invocation/factory.py`
- **Lines:** 118
- **Complexity:** Low
- **Findings:**
  - `create_online` (lines 92-104) is a trivial convenience wrapper around `_create_online_strategy`
  - `create_batch` (lines 107-117) is a trivial wrapper around `BatchStrategy(provider)`
  - These convenience methods add ~25 lines for arguably marginal value

### `recovery/retry.py`
- **Lines:** 258
- **Complexity:** Medium
- **Findings:**
  - **P2-14:** `execute_with_fallback` method (lines 209-234) has zero callers
  - Clean service design with proper error classification

### `recovery/reprompt.py`
- **Lines:** 276
- **Complexity:** Medium
- **Findings:**
  - **P3-18:** f-string logging inconsistent with rest of codebase
  - Well-structured reprompt loop with proper feedback generation

### `recovery/validation.py`
- **Lines:** 145
- **Complexity:** Low
- **Findings:**
  - Thread-safe registry design is appropriate
  - Clean decorator pattern

### `recovery/stats.py`
- **Lines:** 220
- **Complexity:** Low
- **Findings:**
  - **P2-13:** All 5 public functions have zero callers in the codebase
  - Integration guide at bottom (lines 197-219) is still commented out, suggesting this was never integrated
  - Two near-identical `calculate_recovery_stats_from_*` functions (lines 42-85 and 88-132) with slight structural differences (one reads attributes, one reads dict keys)

### `transform/__init__.py`
- **Lines:** 1
- **Complexity:** None
- **Findings:**
  - **P1-5:** Empty package, no purpose

### `strategies/` (directory)
- **Lines:** 0 (source files deleted)
- **Complexity:** None
- **Findings:**
  - **P1-4:** Stale directory with only `__pycache__`

---

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions/errors` | `ConfigurationError`, `ProcessingError`, `ValidationError`, `FileLoadError`, `FileWriteError`, `TransformationError`, `SchemaValidationError`, `AgentActionsException`, `NetworkError`, `RateLimitError`, `VendorAPIError`, `TemplateVariableError` | `processor.py`, `error_handling.py`, `helpers.py`, `result_collector.py`, `retry.py` |
| `agent_actions/logging` | `fire_event`, multiple event types (`TemplateRenderingFailedEvent`, `RecordProcessingStartedEvent`, `RecordFilteredEvent`, `RecordTransformedEvent`, `RecordProcessingCompleteEvent`, `BatchProcessing*Event`, `Enrichment*Event`, `DataParsing*Event`, `RetryExhaustedEvent`, `RepromptValidationFailedEvent`, `ResultCollection*Event`, `DataValidation*Event`) | `processor.py`, `enrichment.py`, `error_handling.py`, `result_collector.py`, `retry.py`, `reprompt.py`, `validation.py` |
| `agent_actions/utils` | `IDGenerator`, `FieldManager`, `LineageBuilder`, `MetadataExtractor`, `VersionIdGenerator`, `PassthroughTransformer`, `resolve_tools_path` | `enrichment.py`, `lineage_mixin.py`, `exhausted_builder.py`, `helpers.py`, `task_preparer.py`, `processor.py` |
| `agent_actions/llm/realtime` | `builder.create_dynamic_agent` | `helpers.py` |
| `agent_actions/input/preprocessing` | `DataTransformer.get_content_by_source_guid`, `get_guard_evaluator` | `processor.py`, `task_preparer.py`, `helpers.py` |
| `agent_actions/prompt` | `PromptPreparationService`, `ContextScopeProcessor` | `processor.py`, `task_preparer.py` |
| `agent_actions/utils/udf_management` | `execute_user_defined_function` | `helpers.py` |
| `agent_actions/storage` (TYPE_CHECKING) | `StorageBackend` | `types.py`, `prepared_task.py`, `task_preparer.py` |
| `agent_actions/validation` | `validate_output_against_schema`, `SchemaValidationReport` | `helpers.py` |
| `agent_actions/utils/constants` | `SCHEMA_KEY`, `STRICT_SCHEMA_KEY` | `helpers.py` |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions/__init__.py` | `reprompt_validation`, `get_validation_function`, `list_validation_functions` (from `recovery/validation.py`) | **High** -- public API surface |
| `agent_actions/workflow/pipeline.py` | `RecordProcessor`, `ResultCollector`, `ProcessingContext`, `ProcessingMode`, `ProcessingResult`, `ProcessingStatus`, `run_dynamic_agent` | **High** -- core workflow engine |
| `agent_actions/input/preprocessing/staging/initial_pipeline.py` | `RecordProcessor`, `ResultCollector`, `ProcessingContext`, `ProcessingMode` | **High** -- staging pipeline |
| `agent_actions/input/preprocessing/processing/data_processor.py` | `transform_with_passthrough`, `ProcessorErrorHandlerMixin` | **Medium** -- data processing |
| `agent_actions/input/loaders/base.py` | `ProcessorErrorHandlerMixin` | **Medium** -- loader base class |
| `agent_actions/input/loaders/file_reader.py` | `ProcessorErrorHandlerMixin` | **Medium** -- file reader |
| `agent_actions/output/writer.py` | `ProcessorErrorHandlerMixin` | **Medium** -- output writer |
| `agent_actions/prompt/data_generator.py` | `RecordProcessor`, `ProcessingContext`, `ProcessingMode`, `ProcessingResult`, `ProcessingStatus` | **High** -- data generation |
| `agent_actions/llm/batch/processing/result_processor.py` | `RecoveryMetadata`, `EnrichmentPipeline`, `BatchContextAdapter`, `ExhaustedRecordBuilder` | **High** -- batch result processing |
| `agent_actions/llm/batch/processing/preparator.py` | `GuardStatus`, `PreparationContext`, `TaskPreparer`, `get_task_preparer` | **High** -- batch task preparation |
| `agent_actions/llm/batch/services/processing.py` | `RecoveryMetadata`, `RetryMetadata`, `RepromptMetadata`, `get_validation_function` | **High** -- batch processing service |

### Dependency Risks

- **P1-2 (delete `lineage_mixin.py`):** Zero downstream risk. No consumers exist.
- **P1-3 (delete `result_adapters.py`):** Low risk. Exported in `__all__` but zero actual consumers. Removing from `__all__` would be a technically breaking API change if any external code imports it.
- **P1-1 (remove dead methods from `processor.py`):** Zero downstream risk. All dead methods are private (`_`-prefixed).
- **P2-8 (refactor `online.py` duplication):** Zero downstream risk. All affected methods are private. `InvocationResult` interface unchanged.
- **P2-11 (error_handling dead methods):** Medium risk. The mixin is inherited by 4 external classes (`FileWriter`, `BaseLoader`, `FileReader`, `DataProcessor`). Must verify those classes (and their subclasses) do not call `with_fallback`, `handle_partial_failure`, or `create_error_recovery_state`.
- **P2-13 (recovery/stats.py potentially dead):** Low risk if removed. No callers, but could be API surface for external tools.
- **P3-25 (consolidate PreparationContext with ProcessingContext):** High risk. Both types are consumed by multiple external modules. Any structural change would cascade.

---

## Recommended Simplification Order

1. **P1-4 + P1-5: Delete empty `strategies/` and `transform/` directories.** Zero risk, instant cleanup. (~0 code lines, removes confusion)

2. **P1-2: Delete `lineage_mixin.py`.** Zero consumers, 172 lines removed. Remove from `_MANIFEST.md` as well.

3. **P1-1: Remove dead private methods from `processor.py`.** Remove `_normalize_input`, `_evaluate_guard`, `_get_source_content`, `_prepare_prompt` (lines 438-635). ~200 lines removed. Leave `_prepare_source_snapshot`, `_transform_response`, `_create_item_context` which are still called.

4. **P1-6 + P3-23: Fix redundant `import logging` in `processor.py` line 399.** Replace with module-level `logger`. 3-line fix.

5. **P1-3: Evaluate removing `result_adapters.py`.** Coordinate with team since it is in `__all__`. If approved, remove file + `__init__.py` entry. 86 lines removed.

6. **P2-10: Remove `hasattr(context, "record_index")` guards in `processor.py`.** 4 one-line simplifications.

7. **P2-17: Extract shared `_prepare_source_snapshot` utility.** Create one copy in a shared location (e.g., `helpers.py` or `types.py`), update both `processor.py` and `task_preparer.py` to use it.

8. **P2-8 + P2-9: Deduplicate `online.py` LLM invocation patterns.** Extract `_build_llm_callable` factory and `_track_retry_metadata` helper. ~80-100 lines deduplication.

9. **P2-12: Fix deprecated `datetime.utcnow()` in `error_handling.py`.** 2-line fix.

10. **P2-15: Evaluate eliminating `processor_init.py`.** Move its one export to `__init__.py` and delete the file. 14 lines removed.

11. **P2-13: Evaluate removing or integrating `recovery/stats.py`.** If integration is not planned, remove; if planned, implement the integration. 220 lines at stake.

12. **P2-14: Remove unused `execute_with_fallback` from `retry.py`.** 25 lines removed.

13. **P2-11: Audit and potentially remove unused mixin methods in `error_handling.py`.** Requires careful verification of all mixin consumers. ~140 lines at stake.

14. **P2-16: Refactor `result_collector.py` status branching.** Use dispatch table or mapping pattern. Moderate effort.

15. **P3 items (18-26):** Address in bulk during a cleanup sweep. Low effort, low risk.
