# Code Simplification Audit: workflow

**Audited path:** `agent_actions/workflow/`
**Date:** 2026-02-05
**Modules reviewed:** 19 (10 top-level, 7 managers, 2 parallel)
**Total lines:** 7,433

## Executive Summary

The workflow folder is the orchestration spine of the project at 7,433 lines across 19 modules. The code has clearly been through deliberate decomposition (extracting managers, strategies, etc.), but that refactoring left behind **significant cross-module duplication** -- particularly three independent copy-pasted implementations of JSON record merging/correlation logic. There are also several dead-code artifacts (`node_mapper.py` is nearly vestigial, `_should_skip_file` is unused, `AgentExecutionContext` is defined but never instantiated). The largest files (`runner.py` at 1,121 lines, `executor.py` at 845 lines) each contain sync/async method pairs that are ~90% identical, accounting for roughly 350+ lines of pure duplication. Estimated savings from addressing P1 and P2 items: **700-900 lines** with reduced maintenance surface.

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

1. **Triplicated JSON merge/correlation logic across runner.py, output.py, and (partially) loop.py**
   - **Files:** `runner.py` lines 442-578 (`_merge_json_contents`, `_merge_records_by_key`, `_deep_merge_record`), `managers/output.py` lines 293-385 (`_merge_json_files` with inline deep merge), `managers/loop.py` lines 388-409 (`_build_correlation_groups` with key resolution)
   - **What:** Three independent implementations of "merge JSON records by correlation key with fallback chain (reduce_key -> parent_target_id -> source_guid), deep-merge content dicts, and deduplicate lineage arrays." The correlation key resolution loop is copy-pasted nearly verbatim in all three locations.
   - **Why:** Any bug fix or behavioral change to merge logic must be applied in three places. This is the single highest-value consolidation in the folder.
   - **Risk:** Low. All three callers want the same behavior. Extract to a shared utility (e.g., `workflow/merge.py` or `utils/merge.py`).
   - **Estimated savings:** ~200 lines.

2. **Sync/async method duplication in executor.py**
   - **File:** `executor.py` lines 201-377 (`execute_agent_sync`) vs. lines 289-377 (`execute_agent_async`)
   - **What:** `execute_agent_sync` and `execute_agent_async` share identical preamble logic (status checks, skip evaluation, skip event firing, run_tracker calls) -- roughly 70 lines copied verbatim. The only difference is `await asyncio.to_thread(...)` vs. a direct call.
   - **Similarly:** `_execute_agent_run` (lines 487-660) vs. `_execute_agent_run_async` (lines 661-822) are ~90% identical (~160 lines duplicated). The async variant wraps calls in `asyncio.to_thread`.
   - **Also:** `_handle_batch_check` (lines 379-414) vs. `_handle_batch_check_async` (lines 416-485) -- identical logic with `asyncio.to_thread` wrapper. The async version also fires extra events that the sync version does not, creating a behavioral inconsistency.
   - **Why:** Roughly 300+ lines of near-identical code. The behavioral inconsistency in event firing between sync and async batch check is a latent bug risk.
   - **Risk:** Low-medium. Refactor to a single internal method that accepts an optional async wrapper/executor. Or use the pattern: extract the shared logic into a private helper, call it from both.
   - **Estimated savings:** ~250-300 lines.

3. **`runner.py` `_should_skip_file` is dead code**
   - **File:** `runner.py` lines 418-427
   - **What:** `_should_skip_file` is defined but never called anywhere in the codebase. The similar `_should_skip_item` (lines 429-440) is the one actually used by `_process_directory_files`.
   - **Why:** Dead code increases cognitive load and can mislead future developers.
   - **Risk:** None. Safe to remove.

4. **`node_mapper.py` is effectively vestigial**
   - **File:** `node_mapper.py` (78 lines)
   - **What:** `NodeMappingService` has three static methods: `build_agent_index_map` (trivial dict comprehension), `get_node_index_for_agent` (wrapper around `dict.get`), and `get_node_directory_name` (returns its argument unchanged). None of these methods are imported or used anywhere in the `agent_actions/` source code. The only callers are in `tests/orchestration/test_node_mapper.py`.
   - **Why:** The docstring says "updated to use simple directory names" -- this was the result of a previous simplification that made the class unnecessary. It adds 78 lines of indirection that provides zero value.
   - **Risk:** Low. Remove the module and its tests.
   - **Estimated savings:** 78 lines + test cleanup.

5. **`AgentExecutionContext` dataclass is unused**
   - **File:** `executor.py` lines 49-56
   - **What:** `AgentExecutionContext` is defined but never instantiated anywhere. `AgentRunParams` (lines 71-78) serves the same purpose and is the one actually used.
   - **Why:** Dead code.
   - **Risk:** None.

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

6. **`runner.py` at 1,121 lines is a god module**
   - **File:** `runner.py`
   - **What:** `AgentRunner` handles directory setup, file processing, merged file processing, storage backend processing, JSON merging, and deep record merging. This is at least three distinct concerns: (a) directory resolution, (b) file iteration/dispatch, (c) record merging/correlation.
   - **Why:** Hard to navigate, hard to test in isolation. The merge logic (finding P1) should be extracted first; the file processing logic could be a separate class.
   - **Risk:** Medium. This is a central module with many callers.

7. **`_merge_json_contents` vs. `_merge_records_by_key` duplication within runner.py**
   - **File:** `runner.py` lines 442-530 (`_merge_json_contents`) vs. lines 579-628 (`_merge_records_by_key`)
   - **What:** These two methods in the same class do nearly the same thing. `_merge_json_contents` reads JSON files and then merges; `_merge_records_by_key` takes pre-loaded records and merges. The correlation key resolution loop (lines 486-506 and 599-619) is identical between them.
   - **Why:** Even within the single file, the merge logic is duplicated. `_merge_json_contents` could simply read the files and delegate to `_merge_records_by_key`.
   - **Risk:** Low. Internal refactor within one class.

8. **`_resolve_upstream_from_manifest` duplicated in runner.py and output.py**
   - **Files:** `runner.py` lines 140-167 (`_resolve_upstream_from_manifest`) and `managers/output.py` lines 387-404 (`_resolve_upstream_from_manifest`)
   - **What:** Near-identical methods that read an upstream manifest and return the upstream path. The runner version returns `List[Path]`, the output version returns `Optional[List[str]]`. Both call `ArtifactLinker.read_manifest()`.
   - **Why:** Duplicated logic that diverges slightly in return types, creating confusion.
   - **Risk:** Low. Consolidate into ArtifactLinker or a shared helper.

9. **`coordinator.py` `_workspace_index` property is dead code**
   - **File:** `coordinator.py` lines 125-135
   - **What:** The `_workspace_index` property (with getter, setter, and `_workspace_index_cached`) is defined on `AgentWorkflow` but never accessed anywhere. Workspace indexing is handled by `WorkflowDependencyOrchestrator.workspace_index` instead.
   - **Why:** Dead code from a previous iteration.
   - **Risk:** None.

10. **`coordinator.py` `_get_status_display` is unused**
    - **File:** `coordinator.py` lines 742-749
    - **What:** `_get_status_display` returns a color/suffix tuple for agent status display, but it is never called anywhere in the codebase. Status display is now handled by the event system.
    - **Why:** Dead code.
    - **Risk:** None.

11. **`dependency.py` `resolve_upstream_and_initialize` is unused**
    - **File:** `parallel/dependency.py` lines 322-354
    - **What:** This method is defined on `WorkflowDependencyOrchestrator` but never called. The coordinator has its own `_resolve_upstream_and_initialize` (lines 532-547) which is a different implementation.
    - **Why:** Dead code from a refactor that moved the initialization logic into the coordinator.
    - **Risk:** None.

12. **`ProcessingPipeline.process_file` static method is unused externally**
    - **File:** `pipeline.py` lines 211-260
    - **What:** `ProcessingPipeline.process_file` is a static method that creates a pipeline and processes a file. However, searching the codebase reveals it is not called from anywhere outside `pipeline.py` itself (the only references are its definition and internal error messages). All callers use either `create_processing_pipeline_from_params` followed by `pipeline.process()`, or the strategy's `_execute_generate_target`.
    - **Why:** Unused code path. The `create_processing_pipeline` factory function (lines 554-567) that takes a `PipelineConfig` is similarly unused externally.
    - **Risk:** Low. Verify with test coverage before removing.

13. **`loop.py` `_extract_correlation_key` is unused**
    - **File:** `managers/loop.py` lines 495-517
    - **What:** This method is defined but never called anywhere in the codebase. The correlation logic uses `version_correlation_id` directly instead.
    - **Why:** Dead code, likely from an earlier iteration of the correlation system.
    - **Risk:** None.

14. **`loop.py` `_load_agent_outputs` is unused**
    - **File:** `managers/loop.py` lines 317-347
    - **What:** This method loads JSON outputs from a directory but is never called. The similar `_load_agent_outputs_with_filenames` (lines 349-386) is the one actually used.
    - **Why:** Dead code. `_load_agent_outputs` is a simpler version that was superseded.
    - **Risk:** None.

### P3 -- Low Impact (Nice-to-have, minor cleanups)

15. **Excessive use of `Any` type in models.py**
    - **File:** `models.py` lines 82-108
    - **What:** `CoreServices` and `SupportServices` dataclasses use `Any` for every field. Similarly `WorkflowConfig.manager` is typed `Any`, `RuntimeContext.console` is `Any`, and `AgentLogParams.result` is `Any`.
    - **Why:** Defeats type-checking and IDE support. The actual types are known and imported elsewhere in the codebase.
    - **Risk:** Low. Change to actual types (possibly with TYPE_CHECKING imports to avoid circular deps).

16. **Inconsistent f-string vs. %-format logging**
    - **Files:** Throughout the folder
    - **What:** Some log statements use f-strings (`logger.info(f"Action '{agent_name}'...")`) while others use %-formatting (`logger.info("Action completed: %s", agent_name)`). The Python logging best practice is %-formatting for lazy evaluation.
    - **Where (examples):** `runner.py` lines 228-229 (f-string), 279-283 (f-string); `coordinator.py` line 384 (f-string in `logger.info`); `pipeline.py` lines 384, 388, 543 (f-strings in `logger.info`/`logger.error`).
    - **Why:** Inconsistency; f-strings in logging always evaluate even when the log level is disabled.
    - **Risk:** None.

17. **Strategies module has vestigial async handling**
    - **File:** `strategies.py` lines 103-111
    - **What:** `_execute_generate_target` checks `asyncio.iscoroutine(result)` after calling `pipeline.process()`. But `pipeline.process()` is a synchronous method that never returns a coroutine.
    - **Why:** Defensive code from a transition period that is no longer needed. It adds complexity without value.
    - **Risk:** Very low.

18. **`strategies.py`: `InitialStrategy` and `StandardStrategy` are trivial single-method wrappers**
    - **File:** `strategies.py` lines 114-174
    - **What:** `InitialStrategy.execute` delegates to `process_initial_stage`, and `StandardStrategy.execute` delegates to `self._execute_generate_target`. Each concrete strategy is 5-10 lines of actual logic. The `runner.py` constructor creates `"intermediate"` and `"terminal"` entries that both use `StandardStrategy`, making the terminal/intermediate distinction meaningless.
    - **Why:** Over-abstraction. The strategy pattern adds indirection for only two behaviors that could be a simple if/else in the runner. However, this is a design choice and may be intentional for extensibility.
    - **Risk:** Very low. Keep if extensibility is planned; otherwise simplify.

19. **`runner.py` `_resolve_linear_directory` has unused parameter**
    - **File:** `runner.py` lines 337-350
    - **What:** The `_idx` parameter is documented as "Unused - kept for API compatibility" but no callers pass a meaningful value.
    - **Why:** Dead parameter.
    - **Risk:** None.

20. **`coordinator.py` `__init__` is 28 lines of initialization with hidden side effects**
    - **File:** `coordinator.py` lines 81-113
    - **What:** The constructor loads configs, validates schemas, initializes storage backend, initializes services, initializes dependency orchestration, generates a session ID, and injects it into configs. This is a chain of side effects including file I/O, database initialization, and console output.
    - **Why:** Hard to test in isolation. Consider a builder or factory pattern.
    - **Risk:** Medium (requires changing callers).

21. **`coordinator.py` `_finalize_workflow` manually counts statuses**
    - **File:** `coordinator.py` lines 781-810
    - **What:** Manually loops through execution_order counting completed/skipped/failed agents. `AgentStateManager.get_summary()` already does this.
    - **Why:** Duplicates existing functionality.
    - **Risk:** None.

22. **`executor.py` sets `error._already_displayed = True` via monkey-patching**
    - **File:** `coordinator.py` line 836
    - **What:** Sets a private attribute on an Exception instance to communicate with the CLI decorator. This is fragile and implicit.
    - **Why:** Implicit inter-module protocol. A dedicated exception subclass or a context variable would be more explicit.
    - **Risk:** Low for cleanup.

23. **Five separate dataclass parameter objects in runner.py**
    - **File:** `runner.py` lines 29-72
    - **What:** `FileProcessParams`, `FileLocationParams`, `SingleFileProcessParams`, `ProcessGenerateParams` -- four dataclasses (plus `StrategyExecutionParams` from strategies.py). `SingleFileProcessParams` wraps `FileLocationParams` plus repeats several fields from `FileProcessParams`.
    - **Why:** Over-decomposition. The nesting and overlap adds cognitive load. Could be simplified.
    - **Risk:** Low.

24. **`manifest.py` mark_action_* methods have repetitive lock-check-update-save pattern**
    - **File:** `managers/manifest.py` lines 315-412
    - **What:** `mark_action_started`, `mark_action_completed`, `mark_action_skipped`, `mark_action_failed`, `mark_workflow_completed`, `mark_workflow_failed` all follow the same pattern: acquire lock, check key exists, set fields, save. The KeyError check + field assignments are repeated with minor variations.
    - **Why:** Could be consolidated with a private `_update_action_status(name, status, **extra_fields)` helper.
    - **Risk:** Very low.

## Module-by-Module Breakdown

### `__init__.py`
- **Lines:** 28
- **Complexity:** Low
- **Findings:** Clean re-export module. No issues.

### `coordinator.py`
- **Lines:** 836
- **Complexity:** High -- orchestrates the entire workflow lifecycle
- **Findings:**
  - P2-9: Dead `_workspace_index` property (lines 125-135)
  - P2-10: Unused `_get_status_display` (lines 742-749)
  - P2-21: `_finalize_workflow` duplicates `AgentStateManager.get_summary()` logic
  - P3-20: Constructor with heavy side effects
  - P3-22: Monkey-patching `error._already_displayed`

### `executor.py`
- **Lines:** 845
- **Complexity:** High -- sync/async duplication dominates
- **Findings:**
  - P1-2: Sync/async method duplication (~300 lines)
  - P1-5: Unused `AgentExecutionContext` dataclass
  - P2 (related): `_handle_batch_check` vs. `_handle_batch_check_async` behavioral inconsistency (async fires events, sync does not)

### `models.py`
- **Lines:** 108
- **Complexity:** Low
- **Findings:**
  - P3-15: Excessive use of `Any` typing in service containers

### `node_mapper.py`
- **Lines:** 78
- **Complexity:** Low
- **Findings:**
  - P1-4: Entire module is vestigial (no source code callers)

### `pipeline.py`
- **Lines:** 605
- **Complexity:** Medium -- pipeline orchestration with batch/online modes
- **Findings:**
  - P2-12: `process_file` static method and `create_processing_pipeline` factory appear unused externally
  - P3-16: f-string logging (lines 384, 388, 543)

### `runner.py`
- **Lines:** 1,121
- **Complexity:** High -- largest file, multiple concerns
- **Findings:**
  - P1-1: Merge logic duplicated with output.py and loop.py
  - P1-3: Dead `_should_skip_file` method (line 418)
  - P2-6: God module with 3+ concerns
  - P2-7: Internal duplication between `_merge_json_contents` and `_merge_records_by_key`
  - P2-8: `_resolve_upstream_from_manifest` duplicated with output.py
  - P3-19: Unused `_idx` parameter in `_resolve_linear_directory`
  - P3-23: Five overlapping parameter dataclasses

### `schema_service.py`
- **Lines:** 237
- **Complexity:** Low-medium
- **Findings:** Well-structured with clear caching pattern. No significant issues found.

### `strategies.py`
- **Lines:** 174
- **Complexity:** Low
- **Findings:**
  - P3-17: Vestigial async coroutine check in `_execute_generate_target`
  - P3-18: Arguably over-abstracted strategy pattern for two behaviors

### `workspace_index.py`
- **Lines:** 162
- **Complexity:** Low-medium -- topological sort implementation
- **Findings:** Clean implementation. No issues found.

### `managers/artifacts.py`
- **Lines:** 189
- **Complexity:** Low
- **Findings:** Well-structured with atomic writes and path validation. No significant issues.

### `managers/batch.py`
- **Lines:** 191
- **Complexity:** Low-medium
- **Findings:** Clean lifecycle management. No significant issues.

### `managers/loop.py`
- **Lines:** 613
- **Complexity:** Medium-high
- **Findings:**
  - P2-13: Dead `_extract_correlation_key` method (line 495)
  - P2-14: Dead `_load_agent_outputs` method (line 317)
  - P1-1 (related): Correlation key resolution logic is similar to merge logic in runner.py

### `managers/manifest.py`
- **Lines:** 467
- **Complexity:** Medium
- **Findings:**
  - P3-24: Repetitive lock-check-update-save pattern in mark_action_* methods

### `managers/output.py`
- **Lines:** 551
- **Complexity:** Medium-high
- **Findings:**
  - P1-1: Contains third copy of JSON merge/correlation logic (lines 293-385)
  - P2-8: `_resolve_upstream_from_manifest` duplicated from runner.py

### `managers/skip.py`
- **Lines:** 330
- **Complexity:** Medium
- **Findings:** Well-designed strategy pattern. Three concrete strategies share similar error handling patterns but not enough to warrant extraction. No significant issues.

### `managers/state.py`
- **Lines:** 194
- **Complexity:** Low
- **Findings:** Clean and well-factored. No issues.

### `parallel/action_executor.py`
- **Lines:** 347
- **Complexity:** Medium
- **Findings:** Clean level-based execution. No significant issues.

### `parallel/dependency.py`
- **Lines:** 357
- **Complexity:** Medium
- **Findings:**
  - P2-11: Dead `resolve_upstream_and_initialize` method (line 322)

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `config/` | `ConfigManager`, `create_agent_runner`, `ProcessorFactory`, `ConfigValidationError` | `coordinator.py`, `runner.py`, `pipeline.py`, `strategies.py` |
| `errors/` | `FileSystemError`, `AgentActionsException`, `ConfigurationError`, `DependencyError`, `ProcessingError`, `DataValidationError`, `WorkflowError` | `runner.py`, `pipeline.py`, `coordinator.py`, `managers/batch.py`, `managers/loop.py`, `managers/output.py`, `workspace_index.py`, `parallel/action_executor.py` |
| `input/` | `FileReader`, `process_initial_stage`, `InitialStageContext`, `discover_udfs`, `get_global_guard_filter`, `FilterItemRequest`, `SourceDataLoader`, `_should_save_source_items` | `pipeline.py`, `strategies.py`, `coordinator.py`, `managers/skip.py`, `managers/loop.py` |
| `output/` | `FileHandler`, `FileWriter`, `OutputHandler` | `runner.py`, `pipeline.py` |
| `llm/` | `ConfigManager` (realtime), `BatchService`, `get_last_usage` | `coordinator.py`, `pipeline.py`, `executor.py` |
| `logging/` | `fire_event`, `get_manager`, event classes | `coordinator.py`, `executor.py`, `managers/batch.py`, `managers/skip.py` |
| `processing/` | `RecordProcessor`, `ResultCollector`, `ProcessingContext`, `ProcessingMode`, `ProcessingResult`, `ProcessingStatus`, `run_dynamic_agent` | `pipeline.py` |
| `models/` | `ActionSchema`, `FieldInfo`, `FieldSource`, `UpstreamReference` | `schema_service.py` |
| `validation/` | `DataFlowGraph`, `DataFlowNode`, `StaticValidationResult`, `WorkflowStaticAnalyzer` | `schema_service.py` |
| `storage/` | `get_storage_backend`, `StorageBackend` (TYPE_CHECKING) | `coordinator.py`, `runner.py`, `pipeline.py`, `strategies.py`, `managers/loop.py`, `managers/output.py` |
| `utils/` | `ensure_path_importable`, `MODEL_VENDOR_KEY`, `safe_format_error` | `coordinator.py`, `pipeline.py` |
| `tooling/` | `ActionCompleteConfig` | `executor.py` |
| `prompt/` | `ContextScopeProcessor` | `runner.py` |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `cli/` | `AgentWorkflow`, `WorkflowConfig`, `WorkflowPaths`, `WorkflowSchemaService` | High -- CLI is the primary user-facing entry point |
| `config/` | `AgentRunner` (from `runner.py`), `WorkflowConfig`, `PipelineConfig` | Medium -- factory creates runners |
| `llm/realtime/` | `WorkflowConfig`, `PipelineConfig` | Medium -- config imports |

### Dependency Risks

- **P1-1 (Merge consolidation):** The merge logic is entirely internal to the workflow folder. Extracting it to a shared utility within `workflow/` has zero cross-folder impact. If placed in `utils/`, other folders could benefit in the future.
- **P1-2 (Sync/async consolidation in executor.py):** The `AgentExecutor` class is consumed by `coordinator.py` only. Refactoring its internals has no external impact as long as `execute_agent_sync` and `execute_agent_async` signatures are preserved.
- **P1-4 (Removing node_mapper.py):** No source code consumers outside of tests. The test file `tests/orchestration/test_node_mapper.py` would need to be removed or archived.
- **P2-6 (Splitting runner.py):** `AgentRunner` is imported by `config/factory.py` and `config/di/application.py`. Any split must preserve the `AgentRunner` public interface (or update both callers).
- **P2-12 (Removing process_file static method):** Verify with test coverage that no tests rely on `ProcessingPipeline.process_file` directly before removal.

## Recommended Simplification Order

1. **Remove dead code first (P1-3, P1-4, P1-5, P2-9, P2-10, P2-11, P2-13, P2-14)** -- Zero risk, immediate reduction of ~200 lines and cognitive load. Can be done in a single PR.

2. **Consolidate merge/correlation logic (P1-1, P2-7)** -- Extract a shared `RecordMerger` utility with `merge_records_by_key()` and `deep_merge_record()`. Update `runner.py`, `managers/output.py`, and `managers/loop.py` to use it. This eliminates the highest-risk duplication. Combine with P2-8 (shared manifest resolution).

3. **Unify sync/async in executor.py (P1-2)** -- Extract shared preamble and result-handling logic into private helpers. This is the largest single-file simplification (~300 lines). Also fix the behavioral inconsistency in batch event firing between sync and async paths.

4. **Decompose runner.py (P2-6)** -- After merge logic is extracted (step 2), split remaining concerns: directory resolution vs. file processing. This depends on steps 1-2 being complete.

5. **Address P3 items** -- Type annotations in models.py, f-string logging cleanup, vestigial async check in strategies.py, manifest mark_action_* consolidation. These are low-effort polish items suitable for opportunistic cleanup.
