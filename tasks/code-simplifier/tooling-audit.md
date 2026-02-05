# Code Simplification Audit: tooling

**Audited path:** `agent_actions/tooling/`
**Date:** 2026-02-05
**Modules reviewed:** 12 (2 `__init__.py`, 5 in `docs/`, 5 in `lsp/`)
**Total lines (Python):** 3,911

## Executive Summary

The `tooling/` directory contains two independent subsystems -- `docs` (documentation generation, catalog building, run tracking) and `lsp` (Language Server Protocol for IDE integration) -- that share no code with each other despite operating on the same domain concepts: workflows, prompts, schemas, and tools. This creates significant duplication in AST-based Python function scanning, schema field extraction, prompt pattern parsing, and YAML block context detection. The `run_tracker.py` module (589 lines) contains the most concentrated internal redundancy: the "empty runs" data structure literal is repeated 5 times, duration calculation logic is inlined 3 times, and the read-modify-write file locking pattern is copy-pasted across 5 methods. The LSP `server.py` (847 lines) is the largest file and functions as a "god module" that mixes protocol wiring, business logic, and several utility functions that duplicate counterparts in `resolver.py`. Overall code health is reasonable for a feature-rich tooling layer, but there are clear opportunities to reduce ~300-400 lines through consolidation.

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

1. **Duplicated "empty runs" data structure in `run_tracker.py`**
   - **File:** `agent_actions/tooling/docs/run_tracker.py`
   - **Lines:** 97-100, 147-150, 161-164, 289-298, 309-318
   - **What:** The dict literal `{"metadata": {"generated_at": ..., "total_runs": 0}, "executions": []}` is defined 5 separate times with slight variations (some include `schema_version`, `workflow_metrics`). The `RunsGenerator.initialize_empty()` in `generator.py` lines 260-272 creates the same structure a 6th time.
   - **Why:** Any schema change to the runs format requires updating 5-6 locations. A single `_empty_runs_data()` factory method would eliminate all duplication and the `RunsGenerator` class entirely.
   - **Risk:** Low. All sites create the same logical structure.

2. **Duplicated read-modify-write locking pattern in `run_tracker.py`**
   - **File:** `agent_actions/tooling/docs/run_tracker.py`
   - **Lines:** 136-141, 302-358, 376-407, 422-436, 490-520
   - **What:** Five methods (`record_run`, `start_workflow_run`, `record_action_start`, `record_action_complete`, `finalize_workflow_run`) each independently open a `portalocker.Lock`, seek(0), json.load, mutate, seek(0), truncate, json.dump. The pattern is identical except for the mutation step.
   - **Why:** This is a textbook "template method" pattern. A single `_atomic_update(self, mutator: Callable)` method that handles locking, loading, saving, and error recovery would reduce ~150 lines and centralize the locking strategy.
   - **Risk:** Low. The locking semantics are identical across all five call sites.

3. **Duplicated duration calculation in `run_tracker.py`**
   - **File:** `agent_actions/tooling/docs/run_tracker.py`
   - **Lines:** 215-222, 256-261, 501-506
   - **What:** The pattern `datetime.fromisoformat(ts.replace("Z", "+00:00"))` followed by `(end - start).total_seconds()` is copy-pasted three times. The class already has `_calculate_duration()` but `_apply_run_updates()` (line 256) and `finalize_workflow_run()` (line 501) inline the same logic instead of calling it.
   - **Why:** The existing `_calculate_duration` method exists precisely for this purpose but is not reused. Inlining creates risk of inconsistent error handling.
   - **Risk:** Very low. Direct replacement with the existing method.

4. **Duplicated `_is_in_*_block` functions between `resolver.py` and `server.py`**
   - **Files:** `agent_actions/tooling/lsp/resolver.py` lines 138-182, `agent_actions/tooling/lsp/server.py` lines 715-759
   - **What:** `_is_in_dependencies_context` / `_is_in_dependencies_block` and `_is_in_context_scope_list` / `_is_in_context_scope_block` implement the same backward-scanning logic to determine if a cursor is inside a YAML block. The implementations differ slightly (resolver uses `list`, server uses `list[str]` typing; resolver checks `startswith("-")`, server does not) but serve the same purpose.
   - **Why:** Four functions doing two things. Consolidate into a shared module (or add to `resolver.py` and import from `server.py`).
   - **Risk:** Low. The functions are pure and stateless.

5. **Duplicated AST-based UDF tool scanning between `docs/scanner.py` and `lsp/indexer.py`**
   - **Files:** `agent_actions/tooling/docs/scanner.py` lines 458-639, `agent_actions/tooling/lsp/indexer.py` lines 488-554
   - **What:** Both modules independently parse Python files with `ast.parse`, walk the tree, find `@udf_tool` decorated functions, extract signatures via `ast.unparse`, and extract docstrings via `ast.get_docstring`. The docs scanner is more thorough (extracts TypedDict schemas, handles `*args`/`**kwargs`) while the LSP indexer is simpler, but the core detection and signature extraction logic is identical.
   - **Why:** ~250 lines of duplicated AST traversal that must stay in sync. A shared `tool_introspector` module could serve both consumers with different levels of detail.
   - **Risk:** Medium. The two consumers need slightly different output shapes (dict vs ToolDefinition dataclass), so the shared layer needs a clean interface.

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

6. **Duplicated schema field extraction between `docs/parser.py` and `lsp/indexer.py`**
   - **Files:** `agent_actions/tooling/docs/parser.py` lines 10-86, `agent_actions/tooling/lsp/indexer.py` lines 577-611
   - **What:** Both extract field names from schema YAML files. `parser.py`'s `extract_fields_for_docs()` handles 3 formats (unified fields, array schema, object schema) and returns rich dicts with `{name, type, description, required}`. The LSP `_extract_schema_fields()` / `_collect_schema_fields()` handles `properties` and `fields` formats but returns a flat list of strings. Neither is aware of the other.
   - **Why:** Schema format support could diverge silently. A shared extraction function returning the rich format, with a thin adapter for the LSP's simpler needs, would keep format support consistent.
   - **Risk:** Medium. Different return types require an adapter.

7. **`lsp/server.py` is a 847-line god module**
   - **File:** `agent_actions/tooling/lsp/server.py`
   - **Lines:** 1-847
   - **What:** This single file contains: server class definition, LSP protocol handlers (initialize, definition, hover, completion, symbols, highlight, semantic tokens, code lens, signature help, diagnostics, save, open), all completion-building helpers, all diagnostic-building helpers, all block-detection helpers, and the CLI entry point.
   - **Why:** At 847 lines and ~25 functions, this module violates single-responsibility. The completion logic (~80 lines), diagnostic logic (~100 lines), and block-detection helpers (~50 lines) could each be extracted into focused modules. This would also make the individual components independently testable.
   - **Risk:** Medium. The server handlers reference the global `server` instance, so extraction requires passing the index explicitly rather than using the module-level singleton.

8. **`run_tracker.py` has two overlapping APIs for starting runs**
   - **File:** `agent_actions/tooling/docs/run_tracker.py`
   - **Lines:** 115-141 (`record_run`) vs 268-360 (`start_workflow_run`)
   - **What:** `record_run` takes a `RunConfig` dataclass and creates a run entry. `start_workflow_run` takes individual kwargs and creates a run entry with a different schema (includes `total_actions`, `successful_actions`, `failed_actions`, `skipped_actions`, `total_tokens`, `actions: {}`). These two methods create incompatible run record shapes in the same JSON file.
   - **Why:** Two different record shapes in the same file are a maintenance hazard. `start_workflow_run` appears to be the newer, richer API, and `record_run` / `RunConfig` may be a legacy path. The downstream consumers (`cli/run.py` uses `RunTracker` and `workflow/executor.py` uses `ActionCompleteConfig`) should be checked to confirm whether `record_run` can be deprecated.
   - **Risk:** Medium. Requires verifying all call sites before removing the older API.

9. **Repeated `Path(uri.replace("file://", ""))` pattern in `lsp/server.py`**
   - **File:** `agent_actions/tooling/lsp/server.py`
   - **Lines:** 61, 123, 273, 278, 305, 402, 435, 447, 502, 566
   - **What:** The URI-to-Path conversion `Path(params.text_document.uri.replace("file://", ""))` appears 10 times. This is also subtly incorrect for URIs with encoded characters or Windows paths.
   - **Why:** A single `_uri_to_path(uri: str) -> Path` helper (or use `urllib.parse.urlparse` + `unquote`) would centralize the conversion and make it correct for edge cases.
   - **Risk:** Low.

10. **`import json` repeated inside methods in `scanner.py`**
    - **File:** `agent_actions/tooling/docs/scanner.py`
    - **Lines:** 179, 263, 359
    - **What:** `json` is imported inside `scan_runs()`, `scan_logs()`, and `_extract_action_metrics()` instead of at the module top level.
    - **Why:** While functionally harmless, this deviates from the project convention of top-level imports and adds visual noise. Moving to the top-level `import` section consolidates the dependency.
    - **Risk:** Very low.

### P3 -- Low Impact (Nice-to-have, minor cleanups)

11. **`docs/site/` directory contains only `.gitkeep`**
    - **File:** `agent_actions/tooling/docs/site/`
    - **What:** An empty directory with a `.gitkeep`. The actual static site is in `docs_site/`. The `site/` directory appears to be vestigial.
    - **Why:** Dead directory adds confusion about where static assets live.
    - **Risk:** Very low.

12. **Unused `Tuple, Type` imports in `run_tracker.py`**
    - **File:** `agent_actions/tooling/docs/run_tracker.py`, line 13
    - **What:** `Tuple` and `Type` are imported from `typing` but the `retry` decorator's type annotations use them. However, since Python 3.9+, `tuple` and `type` builtins can be used directly, making these imports unnecessary if the project targets 3.9+.
    - **Why:** Minor cleanup to align with modern Python idioms.
    - **Risk:** Very low.

13. **`_save_runs` method in `RunTracker` is unused by the newer API**
    - **File:** `agent_actions/tooling/docs/run_tracker.py`, lines 102-113
    - **What:** `_save_runs` uses `portalocker.Lock` with mode `"w"` and timeout 5, while the newer methods use `"r+"` with `LOCK_EX` and timeout 10. `_save_runs` is only called by `update_run()`, which itself uses the older `_load_existing_runs()` (non-atomic read-then-write). This creates a race condition window between the read and the write.
    - **Why:** The `update_run` path is not atomic, unlike `record_run` / `start_workflow_run`. Either fix it to use the atomic pattern or document the limitation.
    - **Risk:** Low (race is unlikely in practice but architecturally inconsistent).

14. **`WorkflowParser.parse_workflow` has a late import**
    - **File:** `agent_actions/tooling/docs/parser.py`, lines 132-133
    - **What:** `from agent_actions.prompt.context.scope import ContextScopeProcessor` is imported inside the for-loop body of `parse_workflow`. This import is re-executed on every call.
    - **Why:** Moving the import to the top of the function (before the loop) or to the module level would be cleaner. The late import may have been intentional to avoid circular imports, but if so, it should have a comment explaining why.
    - **Risk:** Very low.

15. **Broad `except Exception` in `_extract_function_details`**
    - **File:** `agent_actions/tooling/docs/scanner.py`, line 638
    - **What:** `except (SyntaxError, AttributeError, TypeError, IndexError, ValueError)` catches 5 exception types in a single handler that returns `None`. While this is technically specific, the number of caught types suggests the code inside may benefit from more targeted error handling or validation.
    - **Why:** A comment explaining which lines can raise which exceptions would improve maintainability.
    - **Risk:** Very low.

16. **`ProjectIndex.get_schema` is a redundant alias**
    - **File:** `agent_actions/tooling/lsp/models.py`, lines 182-184
    - **What:** `get_schema(name)` just calls `get_schema_path(name)`. The comment says "legacy helper."
    - **Why:** If this is truly legacy with no external callers, it should be removed. If it has callers, they should be migrated to `get_schema_path` or `get_schema_definition`.
    - **Risk:** Very low.

17. **`ActionDefinition` dataclass appears unused**
    - **File:** `agent_actions/tooling/lsp/models.py`, lines 56-65
    - **What:** `ActionDefinition` is defined but never imported or used anywhere in the codebase. `ActionMetadata` (lines 69-88) appears to be its replacement with richer fields.
    - **Why:** Dead code. Can be removed.
    - **Risk:** Very low.

18. **`log_message` override in `DocsRequestHandler` suppresses all HTTP logs**
    - **File:** `agent_actions/tooling/docs/server.py`, lines 52-54
    - **What:** The method override silences all HTTP server logging with no way to re-enable it.
    - **Why:** A `verbose` flag or respecting a log level would be more flexible, but this is a minor UX concern, not a simplification issue.
    - **Risk:** Very low.

## Module-by-Module Breakdown

### `docs/__init__.py`
- **Lines:** 7
- **Complexity:** Minimal
- **Findings:** Clean module. Exports `generate_docs`, `serve_docs`, `RunTracker`, `track_workflow_run`.

### `docs/generator.py`
- **Lines:** 367
- **Complexity:** Moderate. `CatalogGenerator.generate()` (lines 95-253) is 158 lines with a deeply nested loop (3 levels: workflows -> actions -> field enrichment). However, the logic is linear and readable.
- **Findings:**
  - (P1.1) Uses `RunsGenerator.initialize_empty()` which duplicates the runs data structure from `run_tracker.py`.
  - The `generate()` method could be decomposed into `_process_workflow()` and `_compute_stats()` sub-methods for readability.

### `docs/parser.py`
- **Lines:** 251
- **Complexity:** Moderate. `parse_workflow()` (lines 93-216) is 123 lines but is mostly linear key extraction. `extract_fields_for_docs()` has reasonable branching for 3 schema formats.
- **Findings:**
  - (P2.6) `extract_fields_for_docs` duplicates field extraction logic found in `lsp/indexer.py`.
  - (P3.14) Late import of `ContextScopeProcessor` inside the for-loop body.

### `docs/scanner.py`
- **Lines:** 639
- **Complexity:** High. `scan_tool_functions()` delegates to `_extract_typed_dicts()` (50 lines) and `_extract_function_details()` (90 lines) which together form a mini AST analysis framework. `scan_logs()` has a 60-line JSONL parsing loop.
- **Findings:**
  - (P1.5) AST-based tool scanning duplicates `lsp/indexer.py`'s `_index_python_file`.
  - (P2.10) `import json` inside three methods instead of at module top level.

### `docs/run_tracker.py`
- **Lines:** 589
- **Complexity:** High structural redundancy rather than algorithmic complexity. The file has the most concentrated duplication in the folder.
- **Findings:**
  - (P1.1) Empty runs structure literal repeated 5 times.
  - (P1.2) Read-modify-write locking pattern repeated 5 times.
  - (P1.3) Duration calculation inlined 3 times despite `_calculate_duration` existing.
  - (P2.8) Two overlapping run-creation APIs (`record_run` vs `start_workflow_run`).
  - (P3.13) `_save_runs` / `update_run` use non-atomic read-then-write pattern.
  - (P3.12) `Tuple`, `Type` imports could use builtin types on Python 3.9+.

### `docs/server.py`
- **Lines:** 112
- **Complexity:** Low. Clean, well-structured HTTP server.
- **Findings:**
  - (P3.18) `log_message` override silences all logs with no toggle. Minor.

### `lsp/__init__.py`
- **Lines:** 5
- **Complexity:** Minimal
- **Findings:** Exports only `__version__`. No public API from the LSP subpackage itself, which is fine since the LSP is used as a standalone server.

### `lsp/models.py`
- **Lines:** 199
- **Complexity:** Low. Clean dataclass definitions.
- **Findings:**
  - (P3.16) `get_schema` is a redundant alias for `get_schema_path`, marked as "legacy helper."
  - (P3.17) `ActionDefinition` appears unused (superseded by `ActionMetadata`).

### `lsp/indexer.py`
- **Lines:** 611
- **Complexity:** High. `_index_workflow_lines()` (lines 131-383) is 252 lines with 8 state-tracking variables, deeply nested conditionals, and regex matching. This is the most complex function in the folder.
- **Findings:**
  - (P1.5) Tool scanning duplicates `docs/scanner.py`.
  - (P2.6) Schema field extraction duplicates `docs/parser.py`.
  - `_index_workflow_lines` is a candidate for decomposition (the function tracks actions, prompts, tools, schemas, dependencies, context scope, guards, versions, reprompts, and seed files all in one pass). However, decomposing a single-pass line-scanner into sub-functions requires careful state management, so the benefit may not outweigh the complexity of the refactor.

### `lsp/navigator.py`
- **Lines:** 47
- **Complexity:** Low. Clean, focused graph builder.
- **Findings:** No findings. This module is well-structured.

### `lsp/resolver.py`
- **Lines:** 237
- **Complexity:** Moderate. `get_reference_at_position()` (lines 10-135) is 125 lines of sequential pattern matching, which is inherently verbose but clear.
- **Findings:**
  - (P1.4) `_is_in_dependencies_context` and `_is_in_context_scope_list` duplicate functions in `lsp/server.py`.

### `lsp/server.py`
- **Lines:** 847
- **Complexity:** High. Largest file in the folder. Contains ~25 functions mixing LSP protocol handlers with business logic and utility functions.
- **Findings:**
  - (P2.7) God module -- completions, diagnostics, and block-detection helpers should be extracted.
  - (P1.4) `_is_in_dependencies_block` and `_is_in_context_scope_block` duplicate resolver functions.
  - (P2.9) `Path(uri.replace("file://", ""))` repeated 10 times.

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions/output/response/loader.py` | `SchemaLoader.load_schema` | `docs/generator.py` (line 10), `docs/scanner.py` (line 10) |
| `agent_actions/prompt/context/scope.py` | `ContextScopeProcessor.infer_dependencies` | `docs/parser.py` (line 132, late import) |
| `agent_actions/utils/constants.py` | `SPECIAL_NAMESPACES` | `lsp/server.py` (line 10) |
| `agent_actions/__version__.py` | `__version__` | `lsp/__init__.py` (line 3) |
| `lsprotocol` (external) | `types` | `lsp/server.py` |
| `pygls` (external) | `LanguageServer` | `lsp/server.py` |
| `ruamel.yaml` (external) | `YAML` | `lsp/indexer.py` |
| `portalocker` (external) | `Lock`, `LOCK_EX`, `exceptions.LockException` | `docs/run_tracker.py` |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions/cli/docs.py` | `generate_docs`, `serve_docs` | Medium -- these are the primary public entry points for the docs CLI commands |
| `agent_actions/cli/run.py` | `RunTracker` | Medium -- run tracking is integral to workflow execution |
| `agent_actions/workflow/executor.py` | `ActionCompleteConfig` | Medium -- dataclass is used as a protocol boundary |
| `agent_actions/validation/static_analyzer/schema_extractor.py` | `ProjectScanner` | Low -- uses scanner for static analysis |
| `tests/unit/tooling/lsp/test_server_smoke.py` | `server` module | Low -- test dependency |

### Dependency Risks

- **P1.1 (empty runs structure):** The `RunsGenerator` class is only called from `generator.py` line 332. If consolidated into `RunTracker`, the import in `generator.py` needs updating, and the `docs/__init__.py` export can remain unchanged.
- **P1.2 (atomic update pattern):** Refactoring the locking pattern is internal to `run_tracker.py` and does not change the public API (`record_run`, `start_workflow_run`, `record_action_complete`, `finalize_workflow_run`). No downstream impact.
- **P1.5 (shared tool scanning):** Creating a shared module would require both `docs/scanner.py` and `lsp/indexer.py` to import from it. This creates a new cross-sub-module dependency within `tooling/`, which is architecturally acceptable since both are within the same package.
- **P2.7 (server decomposition):** The LSP server is consumed only by `tests/` and the CLI entry point (`main()`). Splitting it into sub-modules has no external impact as long as the `server` instance remains importable from the same path.
- **P2.8 (dual run APIs):** `ActionCompleteConfig` is imported by `workflow/executor.py`. `RunConfig` is used by the convenience function `track_workflow_run` (exported from `docs/__init__.py`). Deprecating `record_run` / `RunConfig` requires verifying no external callers remain.

## Recommended Simplification Order

1. **P1.1 + P1.3 -- Consolidate runs data structure and duration calculation in `run_tracker.py`** (lowest risk, highest duplication density). Extract `_empty_runs_data()` factory and reuse `_calculate_duration()` everywhere. Remove `RunsGenerator` from `generator.py`. Estimated reduction: ~40 lines.

2. **P1.2 -- Extract atomic file update helper in `run_tracker.py`**. Create `_atomic_update(self, mutator: Callable[[Dict], Any])` that encapsulates the lock-read-mutate-write pattern. Refactor all five call sites. Estimated reduction: ~100 lines.

3. **P1.4 -- Consolidate `_is_in_*_block` helpers in LSP**. Move the canonical implementations to `resolver.py` (or a new `lsp/utils.py`) and import from `server.py`. Estimated reduction: ~30 lines.

4. **P2.9 -- Extract `_uri_to_path` helper in LSP server**. Single function to replace 10 inline conversions. Estimated reduction: ~10 lines, improved correctness.

5. **P1.5 -- Create shared `tooling/tool_scanner.py`** for AST-based UDF function extraction. Both `docs/scanner.py` and `lsp/indexer.py` import from it. This is the largest refactor and should be done after items 1-4 are stable. Estimated reduction: ~100 lines.

6. **P2.6 -- Create shared schema field extraction**. Lower priority than tool scanning because the two implementations handle different output formats.

7. **P2.7 -- Decompose `lsp/server.py`**. Extract `completions.py`, `diagnostics.py` from the server module. This is a structural improvement that does not reduce line count much but improves testability and readability.

8. **P2.8 -- Audit and potentially deprecate `record_run` / `RunConfig`**. Requires checking all call sites. Do this last as it affects the public API.

9. **P3 items** can be addressed opportunistically alongside the above changes.
