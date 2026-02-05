# Code Simplification Audit: prompt

**Audited path:** `agent_actions/prompt/`
**Date:** 2026-02-05
**Modules reviewed:** 11 (8 top-level + 3 in `context/` sub-module)
**Total lines:** 4,652

## Executive Summary

The `prompt/` folder is the second-largest subsystem in the codebase (4,652 lines) and serves as the central hub for prompt preparation, template rendering, context building, and configuration loading. The highest-impact simplification targets are: (1) the 1,589-line `context/scope.py` god module which contains a single class with deeply nested methods exceeding 400 lines; (2) duplicated YAML-parsing logic across two classes in `renderer.py`; (3) two completely separate field-reference systems (`PromptUtils.parse_field_references` and `ContextScopeProcessor.parse_field_reference`) that solve overlapping problems with different implementations; and (4) excessive defensive logging in `scope.py` that accounts for roughly 25% of the file's bulk. Estimated effort: 3-5 days of focused refactoring for P1 items, 2-3 days for P2 items.

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

1. **`context/scope.py` -- God class `ContextScopeProcessor` (1,589 lines, 20+ methods)**
   **File:** `agent_actions/prompt/context/scope.py`, lines 30-1589
   **What:** A single class with 20+ static methods handling dependency inference, field context building, context scope application, version detection, historical node loading, field filtering, and passthrough merging. The `build_field_context_with_history()` method alone spans lines 1112-1589 (477 lines) with 6+ levels of nesting.
   **Why:** Violates single responsibility principle. The class mixes dependency graph analysis, data loading, field filtering, and namespace management. Testing, reasoning about, and modifying any one concern risks breaking others.
   **Risk:** Medium -- method is heavily used downstream; split must preserve all public method signatures.

2. **`context/scope.py:build_field_context_with_history()` -- 477-line method with extreme nesting**
   **File:** `agent_actions/prompt/context/scope.py`, lines 1112-1589
   **What:** Single method with 6+ levels of nesting (`if batch_mode_enabled` > `if version_namespaces_detected` > `for version_name, version_data` > `if allowed_fields is None` > ...). Contains duplicated field-filtering logic (wildcard vs specific) in at least 4 separate code blocks (lines 1275-1293, 1327-1343, 1360-1384, 1484-1508).
   **Why:** Near-impossible to unit test individual branches. The duplicated wildcard/specific filtering pattern should be a single helper.
   **Risk:** Low for extracting helpers, medium for restructuring control flow.

3. **`renderer.py` -- Duplicated `_safe_load_yaml` implementations**
   **File:** `agent_actions/prompt/renderer.py`, lines 282-310 and 496-522
   **What:** Two separate `_safe_load_yaml` methods exist: one on `ConfigRenderingService` (line 282) and one on `ConfigRenderer` (line 496). Both parse YAML and convert errors, but with different error types (`ConfigurationError` vs `ConfigValidationError`), different empty-handling semantics (`raise` vs `return {}`), and different null-mark handling.
   **Why:** Behavioral divergence creates maintenance risk. Both are trying to do the same thing with inconsistent outcomes.
   **Risk:** Low -- `ConfigRenderer._safe_load_yaml` is dead code (never called; `render_and_load_config` is `@staticmethod` and delegates to `ConfigRenderingService`).

4. **`renderer.py` -- `ConfigRenderer._safe_load_yaml` is dead code**
   **File:** `agent_actions/prompt/renderer.py`, lines 495-522
   **What:** `ConfigRenderer._safe_load_yaml` is an instance method, but `ConfigRenderer.render_and_load_config` is a `@staticmethod` that creates a `ConfigRenderingService` instance and delegates. No code path ever instantiates `ConfigRenderer` to call `_safe_load_yaml`.
   **Why:** Dead code adds confusion and maintenance burden.
   **Risk:** Very low -- confirmed unused via grep across codebase.

5. **`context/scope.py` -- Repeated inline `from agent_actions.errors import ConfigurationError` (5 occurrences)**
   **File:** `agent_actions/prompt/context/scope.py`, lines 372, 405, 999, 1093, 1525
   **What:** `ConfigurationError` is imported 5 times inside method bodies to "avoid circular imports." However, it is used across most code paths, so the circular-import avoidance is likely stale.
   **Why:** Moves the import from a single top-level location to 5 scattered locations, making it easy to miss and harder to refactor.
   **Risk:** Low -- verify no circular import actually exists, then move to top-level.

6. **Duplicated field-filtering pattern (wildcard vs specific) across 4+ locations in `scope.py`**
   **File:** `agent_actions/prompt/context/scope.py`, lines ~1275-1293, 1327-1343, 1360-1384, 1484-1508
   **What:** The same logic appears 4+ times:
   ```python
   if allowed_fields is None:
       field_context[name] = data  # wildcard
   else:
       filtered_data = {field: data[field] for field in allowed_fields if field in data}
       field_context[name] = filtered_data
   ```
   **Why:** Classic extract-method candidate. A single `_filter_and_store_fields(field_context, name, data, allowed_fields)` helper would eliminate all duplication.
   **Risk:** Very low.

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

7. **Two separate field-reference systems that solve overlapping problems**
   **File:** `agent_actions/prompt/prompt_utils.py` lines 136-224 (`PromptUtils.parse_field_references` / `replace_field_references`) and `agent_actions/prompt/context/scope.py` line 41 (`ContextScopeProcessor.parse_field_reference`)
   **What:** `PromptUtils` uses regex `\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)\}` to parse `{ref.field}` patterns and replace them. `ContextScopeProcessor` uses string `.split(".", 1)` to parse `action.field` references. These solve the same conceptual problem (resolving dotted field references) with completely different APIs and error handling.
   **Why:** Developers must understand two separate reference systems. The `PromptUtils` version is used for legacy `{ref.field}` patterns while the `ContextScopeProcessor` version is used for `context_scope` directives. Consolidating the parsing logic (not necessarily the usage) would reduce cognitive load.
   **Risk:** Medium -- different callers depend on different return formats.

8. **`renderer.py` -- Over-abstracted Strategy pattern (3 ABC interfaces, 3 implementations, used only by 1 service)**
   **File:** `agent_actions/prompt/renderer.py`, lines 32-87 (ABCs), 89-188 (implementations), 261-489 (service)
   **What:** `TemplateRenderer`, `ConfigParser`, `OutputWriter` ABCs plus `JinjaTemplateRenderer`, `YAMLConfigParser`, `FileOutputWriter` implementations. Only `ConfigRenderingService` ever uses them, and only with default implementations. No test or production code injects alternative implementations.
   **Why:** Classic over-engineering. The Strategy pattern adds 6 classes where direct method calls would suffice. `YAMLConfigParser.parse()` is also never called (the service uses `_safe_load_yaml` instead, bypassing it entirely).
   **Risk:** Low-medium -- `JinjaTemplateRenderer.render()` is called by the service, but `YAMLConfigParser.parse()` and `FileOutputWriter.write()` appear unused by external callers.

9. **`renderer.py:JinjaTemplateRenderer.render()` -- 72-line method doing validation + rendering + file writing**
   **File:** `agent_actions/prompt/renderer.py`, lines 92-188
   **What:** Single method that creates a PathValidator, validates 3 paths, constructs error messages, calls `render_pipeline_with_templates`, and writes the output file. Zero separation of concerns.
   **Why:** Hard to test rendering in isolation from file I/O and validation. Method has 5 levels of nesting.
   **Risk:** Low -- straightforward decomposition.

10. **`service.py:_render_prompt_template()` -- 78-line error-handling block with deeply nested helper function**
    **File:** `agent_actions/prompt/service.py`, lines 465-584
    **What:** The `except Exception` block (lines 516-584) defines a nested function `_collect_refs_with_namespace` (line 523), does recursive namespace collection, regex matching, event firing, and exception wrapping. This error-handling code is longer than the happy path.
    **Why:** Error-handling code is harder to test when it's deeply interleaved with processing logic. The namespace-collection helper could be a module-level function.
    **Risk:** Low -- only changes error reporting code path.

11. **`service.py` -- Duplication between `prepare_prompt_with_context()` and `prepare_prompt_with_field_context()`**
    **File:** `agent_actions/prompt/service.py`, lines 127-202 and 205-305
    **What:** Steps 4-7 (context scope application, LLM context building, template rendering, function injection) are nearly identical between the two methods, differing only in how field_context is obtained (built vs pre-loaded).
    **Why:** Changes to the pipeline (e.g., adding a new step) must be made in two places.
    **Risk:** Low -- refactor to share a common tail after field_context is obtained.

12. **`handler.py` -- Duplicated regex pattern compilation**
    **File:** `agent_actions/prompt/handler.py`, lines 55 and 78
    **What:** `re.compile("\\{prompt\\s+(\\w+)\\}")` is compiled identically at lines 55 (`get_all_prompt_names`) and 78 (`validate_prompt_blocks`). Should be a class-level constant.
    **Why:** Minor performance waste on re-compilation, and the two patterns could drift if one is updated and the other is not.
    **Risk:** Very low.

13. **`render_workflow.py` -- `normalize_yaml_indentation()` is a no-op**
    **File:** `agent_actions/prompt/render_workflow.py`, lines 33-54
    **What:** The function calls `textwrap.dedent(yaml_text)` then immediately `splitlines(keepends=True)` and re-joins with `"".join(lines)`. The splitlines+join is a no-op (produces the same string). The entire function is equivalent to just `textwrap.dedent(yaml_text)`.
    **Why:** The "fixes" described in the docstring (inconsistent list item spacing, preserving relative indentation) are not actually implemented. The function does nothing beyond `textwrap.dedent`.
    **Risk:** Very low -- replace with direct `textwrap.dedent` call.

14. **`context/scope.py:_extract_allowed_fields_per_dependency()` -- 100-line method with O(n*m) nested loop**
    **File:** `agent_actions/prompt/context/scope.py`, lines 970-1108
    **What:** For each dependency, iterates over ALL field references, re-parsing each one. With D dependencies and R references, this is O(D*R) parse operations. The outer loop (lines 1042-1106) re-parses every field_ref that was already parsed in the preliminary loop (lines 1024-1040).
    **Why:** The method could parse all references once into a dict keyed by action name, then look up each dependency in O(1).
    **Risk:** Low -- pure algorithmic improvement, no behavioral change.

### P3 -- Low Impact (Nice-to-have, minor cleanups)

15. **`render_workflow.py:_load_template_globals()` -- Uses `print()` instead of logger**
    **File:** `agent_actions/prompt/render_workflow.py`, line 72
    **What:** `print(f"Warning: Template file '{template_file}' not found...")` instead of `logger.warning(...)`.
    **Why:** Inconsistent with all other logging in the module. `print` output may not be captured by logging frameworks.
    **Risk:** Very low.

16. **`formatter.py` -- Inline imports with stale "New modular pattern!" comments**
    **File:** `agent_actions/prompt/formatter.py`, lines 35 and 67
    **What:** `from agent_actions.errors import PromptValidationError  # New modular pattern!`
    **Why:** The "New modular pattern!" comment is a migration artifact, not useful documentation. Should be removed or replaced with a "why" comment if the inline import is intentional (circular import avoidance).
    **Risk:** Very low.

17. **`static_loader.py` -- Stale "New modular pattern!" comment**
    **File:** `agent_actions/prompt/context/static_loader.py`, line 15
    **What:** `from agent_actions.errors import FileSystemError  # New modular pattern!` -- same pattern as formatter.py.
    **Why:** Same as finding #16.
    **Risk:** Very low.

18. **`prompt_utils.py:process_dispatch_in_text()` -- Redundant `raise e` pattern**
    **File:** `agent_actions/prompt/prompt_utils.py`, lines 67-68 and 91-92
    **What:** `except (AgentActionsException, ConfigurationError) as e: raise e` -- catching an exception only to re-raise it is redundant.
    **Why:** Adds 2 lines per occurrence with no behavioral effect. The exceptions would propagate naturally without this clause.
    **Risk:** Very low. Note: this pattern does prevent the subsequent generic `except Exception` from catching these types, so removing requires moving to a more specific catch order or using `if isinstance` checks. The simplest fix is to keep the catch but just use `raise` without `e`.

19. **`context/scope.py:extract_field_names_from_references()` -- Unused `_return_type` parameter**
    **File:** `agent_actions/prompt/context/scope.py`, line 84
    **What:** Parameter `_return_type: str = "list"` is never used in the method body. Only `"list"` is supported per the docstring.
    **Why:** Dead parameter adds confusion to the API.
    **Risk:** Very low -- check no callers pass it (confirmed: no callers pass `_return_type`).

20. **`context/scope.py` -- f-string logging vs %-formatting inconsistency**
    **File:** `agent_actions/prompt/context/scope.py` (throughout) and `agent_actions/prompt/render_workflow.py` (lines 304, 310, 318, 324, 330)
    **What:** `scope.py` uses `logger.debug("...", args)` (%-formatting) consistently, which is correct. But `render_workflow.py` uses `logger.debug(f"...")` and `logger.warning(f"...")` with f-strings (5 occurrences). Within `scope.py`, the deeply nested methods mix `logger.debug(f"...")` in inline f-strings with the correct `%` format.
    **Why:** f-string logging evaluates the format expression even when the log level is disabled, causing unnecessary work. The project should consistently use %-formatting for logging.
    **Risk:** Very low.

21. **`context/scope.py:build_field_context_with_history()` -- `"allowed_fields_map" not in locals()` anti-pattern**
    **File:** `agent_actions/prompt/context/scope.py`, line 1395
    **What:** `if "allowed_fields_map" not in locals():` is used to conditionally compute `allowed_fields_map`. This is a code smell indicating the variable's lifetime is unclear.
    **Why:** Using `locals()` inspection to check variable binding is fragile and confusing. Should restructure so the variable is always computed at one point.
    **Risk:** Very low.

22. **`data_generator.py` -- Naming clash `ProcessingMode` imported from two packages**
    **File:** `agent_actions/prompt/data_generator.py`, lines 15 and 18-19
    **What:** `from agent_actions.config.interfaces import ProcessingMode` (line 15) and `from agent_actions.processing.types import ProcessingMode as CoreProcessingMode` (line 19). The alias `CoreProcessingMode` suggests the two types are different but conceptually similar, creating confusion.
    **Why:** Two `ProcessingMode` types in the same file is a naming collision that requires constant mental mapping.
    **Risk:** Very low (renaming the alias is safe).

23. **`context/scope.py` -- Excessive debug logging (estimated 80+ `logger.debug` calls)**
    **File:** `agent_actions/prompt/context/scope.py`, throughout
    **What:** The file contains approximately 80+ `logger.debug(...)` calls. Many are duplicative (e.g., lines 1200-1217 log nearly identical information in 5 consecutive calls). Several use the pattern `[TAG] Action 'X': field=Y` which adds prefix noise.
    **Why:** While debug logging is valuable, 80+ calls in a single file creates log noise even at DEBUG level and significantly inflates the file size. Many could be consolidated.
    **Risk:** Very low -- consolidate verbose sequential debug calls.

24. **`service.py:PromptPreparationRequest` dataclass has identical fields to `prepare_prompt_with_context()` signature**
    **File:** `agent_actions/prompt/service.py`, lines 31-69 and 127-143
    **What:** The `PromptPreparationRequest` dataclass exactly mirrors the method signature of `prepare_prompt_with_context()`, which immediately constructs a request object and delegates. The dataclass adds a layer of indirection.
    **Why:** Debatable whether this is over-engineering or good practice. The dataclass is only used internally by `_prepare_prompt_internal()`. However, it does serve a documentation purpose and makes the internal method signature clean.
    **Risk:** Low -- this is a style judgment call. The current pattern is acceptable but worth noting.

25. **`context/scope.py:expand_version_base_names()` -- Nested function definition inside `infer_dependencies()`**
    **File:** `agent_actions/prompt/context/scope.py`, lines 485-522
    **What:** A 37-line function `expand_version_base_names()` is defined inside `infer_dependencies()`. It captures `workflow_actions` from the enclosing scope.
    **Why:** Nested function definitions inside already-large methods increase cognitive load. This could be a static method or module-level function with `workflow_actions` as an explicit parameter.
    **Risk:** Very low.

26. **`context/scope.py:_detect_version_namespaces()` -- Redundant `input_sources` membership check**
    **File:** `agent_actions/prompt/context/scope.py`, lines 909-967
    **What:** The method first checks `if key in input_sources` (line 946) and then falls through to check `if any(src.startswith(...) for src in input_sources)` (line 956). The logic could be simplified with a single pass using a pre-built set of base names.
    **Why:** Readability improvement. The current nested conditionals make it hard to follow the detection logic.
    **Risk:** Very low.

27. **Missing `context/__init__.py`**
    **File:** `agent_actions/prompt/context/` (directory)
    **What:** The `context/` sub-package has no `__init__.py` file. It relies on implicit namespace packages (PEP 420).
    **Why:** While technically valid in Python 3.3+, explicit `__init__.py` is the project convention (the parent `prompt/` directory has one). Inconsistency could cause issues with some tooling.
    **Risk:** Very low.

28. **`service.py:_determine_static_data_dir()` -- 65-line method with complex path traversal**
    **File:** `agent_actions/prompt/service.py`, lines 684-768
    **What:** Multi-level path discovery (workflow-level, then project-level) with a while-loop traversing the filesystem upward. Contains `if "workflow_seed_dir" in locals()` pattern.
    **Why:** The path traversal logic is complex and fragile. The `locals()` check (line 751) is the same anti-pattern as finding #21.
    **Risk:** Low -- path discovery is inherently complex, but the method could be decomposed.

## Module-by-Module Breakdown

### `__init__.py`
- **Lines:** 0 (empty)
- **Complexity:** None
- **Findings:** No public API exported. Consider whether key symbols should be re-exported for convenience.

### `data_generator.py`
- **Lines:** 163
- **Complexity:** Low-moderate. Single class with 3 methods. `create_agent_with_data()` has 4-way if/elif/elif/else on status enum.
- **Findings:** [P3 #22] Naming clash with two `ProcessingMode` imports.

### `formatter.py`
- **Lines:** 77
- **Complexity:** Low. Two static methods with straightforward logic.
- **Findings:** [P3 #16] Stale "New modular pattern!" inline import comments. Both methods are thin wrappers that delegate immediately to `PromptLoader` and `PromptUtils` -- could arguably be eliminated (see P2 #7 on two field-reference systems).

### `handler.py`
- **Lines:** 124
- **Complexity:** Low. Four static methods for prompt loading/validation.
- **Findings:** [P2 #12] Duplicated regex compilation at lines 55 and 78.

### `prompt_utils.py`
- **Lines:** 224
- **Complexity:** Moderate. `process_dispatch_in_text()` has branching logic for type preservation vs string replacement.
- **Findings:** [P2 #7] Overlapping field-reference system with `scope.py`. [P3 #18] Redundant `raise e` pattern (lines 67-68, 91-92).

### `render_workflow.py`
- **Lines:** 635
- **Complexity:** Moderate. Well-decomposed into focused functions. The main `render_pipeline_with_templates()` orchestrates a clear 5-step pipeline.
- **Findings:** [P2 #13] `normalize_yaml_indentation()` is effectively a no-op beyond `textwrap.dedent`. [P3 #15] `print()` used instead of `logger.warning()`. [P3 #20] f-string logging (5 occurrences). Overall this module is relatively well-structured.

### `renderer.py`
- **Lines:** 542
- **Complexity:** High. 9 classes (3 ABCs + 3 implementations + `ConfigRenderingService` + `ConfigRenderer` + their methods). `JinjaTemplateRenderer.render()` is 72 lines.
- **Findings:** [P1 #3, #4] Duplicated/dead `_safe_load_yaml`. [P2 #8] Over-abstracted Strategy pattern. [P2 #9] Monolithic `render()` method. `YAMLConfigParser.parse()` is unused by the service (it uses `_safe_load_yaml` instead).

### `service.py`
- **Lines:** 772
- **Complexity:** High. Large `PromptPreparationService` class with complex error handling and multiple code paths for batch vs realtime.
- **Findings:** [P2 #10] 78-line error handler with nested function. [P2 #11] Duplication between two `prepare_prompt_*` methods. [P3 #24] Questionable dataclass indirection. [P3 #28] Complex `_determine_static_data_dir` with `locals()` anti-pattern.

### `context/builder.py`
- **Lines:** 163
- **Complexity:** Low. Clean implementation with shared `_build_llm_context` method and two thin wrappers. Well-documented.
- **Findings:** No significant issues. This module is an example of good decomposition.

### `context/scope.py`
- **Lines:** 1,589
- **Complexity:** Very high. Single class with 20+ methods. `build_field_context_with_history()` is 477 lines. Multiple 5+ nesting levels.
- **Findings:** [P1 #1, #2, #5, #6] God class, mega-method, scattered imports, duplicated filtering. [P2 #14] O(n*m) field extraction. [P3 #19, #20, #21, #23, #25, #26] Various cleanup items.

### `context/static_loader.py`
- **Lines:** 363
- **Complexity:** Low-moderate. Well-structured loader with clear single responsibility. Good error handling with specific error types.
- **Findings:** [P3 #17] Stale "New modular pattern!" comment. The per-format loader methods (`_load_json`, `_load_yaml`, `_load_csv`, `_load_text`) follow a repetitive pattern but are short enough that extracting a common wrapper might not improve readability.

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions/output/response/` | `AgentEntryDict`, `AgentConfigMap`, `AgentConfig` | `data_generator.py`, `renderer.py` |
| `agent_actions/config/interfaces` | `IGenerator`, `ProcessingMode` | `data_generator.py` |
| `agent_actions/config/di/container` | `registry` | `data_generator.py` |
| `agent_actions/processing/` | `RecordProcessor`, `ProcessingContext`, `ProcessingMode`, `ProcessingStatus` | `data_generator.py` |
| `agent_actions/errors/` | `GenerationError`, `TemplateRenderingError`, `ConfigurationError`, `ConfigValidationError`, `PromptValidationError`, `FileSystemError`, `AgentActionsException`, `TemplateVariableError` | Multiple modules |
| `agent_actions/utils/` | `PROMPT_KEY`, `SPECIAL_NAMESPACES`, `ErrorHandler`, `ServiceLogger`, `safe_format_error` | `formatter.py`, `renderer.py`, `render_workflow.py`, `scope.py` |
| `agent_actions/input/preprocessing/` | `StringProcessor`, `DataTransformer` | `prompt_utils.py`, `builder.py` |
| `agent_actions/input/context/historical` | `HistoricalNodeDataLoader`, `HistoricalDataRequest` | `scope.py` |
| `agent_actions/output/file_handler` | `FileHandler` | `handler.py` |
| `agent_actions/validation/` | `ConfigValidator`, `PathValidator`, `SchemaValidator` | `renderer.py` |
| `agent_actions/llm/realtime/handlers` | `AgentManager` | `renderer.py` |
| `agent_actions/logging/` | `fire_event`, various event types | `service.py`, `scope.py`, `static_loader.py` |
| `agent_actions/config/paths` | `PathManager`, `PathType`, `ProjectRootNotFoundError` | `service.py` |
| `agent_actions/storage/backend` | `StorageBackend` (TYPE_CHECKING) | `data_generator.py`, `service.py`, `scope.py` |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions/cli/` (`run.py`, `schema.py`, `inspect.py`, `compile.py`) | `ConfigRenderer`, `render_pipeline_with_templates`, `ContextScopeProcessor` | **High** -- CLI entry points depend on `ConfigRenderer` facade |
| `agent_actions/processing/` (`processor.py`, `task_preparer.py`) | `PromptPreparationService`, `ContextScopeProcessor` | **High** -- core processing pipeline |
| `agent_actions/llm/batch/processing/` (`preparator.py`, `result_processor.py`) | `PromptFormatter`, `ContextScopeProcessor` | **High** -- batch LLM pipeline |
| `agent_actions/llm/realtime/` (`builder.py`, `config.py`, `services/`) | `ContextScopeProcessor`, `PromptPreparationService`, `PromptFormatter`, `StaticDataLoader`, `render_pipeline_with_templates` | **High** -- realtime LLM pipeline |
| `agent_actions/output/response/` (`schema.py`, `loader.py`) | `PromptUtils`, `render_pipeline_with_templates` | Medium |
| `agent_actions/config/di/` (`configurator.py`, `application.py`) | `DataGenerator`, `PromptLoader` | Medium |
| `agent_actions/workflow/runner.py` | `ContextScopeProcessor` | Medium |
| `agent_actions/validation/` (`static_analyzer/`, `prompt.py`, `prompt_validator.py`) | `ContextScopeProcessor`, `PromptLoader` | Medium |
| `agent_actions/input/preprocessing/` (`context_provider.py`, `initial_pipeline.py`) | `ContextScopeProcessor`, `PromptFormatter`, `PromptPreparationService` | Medium |
| `agent_actions/tooling/docs/parser.py` | `ContextScopeProcessor` | Low |
| `agent_actions/utils/transformation/strategies/context_scope.py` | `ContextScopeProcessor` | Low |
| `tests/` (8+ test files) | `ContextScopeProcessor`, `LLMContextBuilder`, `PromptUtils`, `PromptPreparationService`, `render_pipeline_with_templates` | N/A (tests) |

### Dependency Risks

- **`ContextScopeProcessor` is the most widely consumed symbol** (imported by 14+ files across 8 folders). Any refactoring of this class must preserve all public method signatures or coordinate changes across the entire codebase. Splitting the god class (P1 #1) should use a re-export strategy from the current module path.
- **`ConfigRenderer` is the CLI's sole entry point** for config loading. The facade pattern (line 492-542) exists specifically for backward compatibility. Removing the dead `_safe_load_yaml` (P1 #4) is safe, but the `render_and_load_config` static method must remain.
- **`PromptFormatter` is used by batch and realtime paths**. The thin-wrapper nature of this class (P3 finding) means changes to `PromptLoader` or `PromptUtils` propagate through it transparently.
- **`render_pipeline_with_templates` is called by CLI compile, config loader, and renderer.py**. Changes to the rendering pipeline (P2 #13 no-op function) are low-risk but should verify all 3 callers still behave correctly.
- **`renderer.py` imports `AgentManager.find_project_root`** from `agent_actions/llm/realtime/handlers` (line 21). This creates a surprising coupling where the prompt renderer depends on the LLM realtime handlers package. This cross-cutting dependency should be noted if the renderer is simplified (P2 #8).

## Recommended Simplification Order

1. **[P1 #4] Remove dead `ConfigRenderer._safe_load_yaml`** -- Zero risk, immediate code reduction. (Est: 15 min)

2. **[P1 #6] Extract field-filtering helper in `scope.py`** -- Create `_filter_fields(data, allowed_fields) -> dict` to eliminate 4 duplicated blocks. (Est: 30 min)

3. **[P1 #5] Move `ConfigurationError` imports to top-level in `scope.py`** -- Verify no circular import exists, then consolidate 5 inline imports to 1 top-level import. (Est: 15 min)

4. **[P2 #13] Replace `normalize_yaml_indentation` with `textwrap.dedent`** -- The function is a no-op wrapper. (Est: 10 min)

5. **[P2 #12] Extract regex constant in `handler.py`** -- `PROMPT_PATTERN = re.compile(r"\{prompt\s+(\w+)\}")` at class level. (Est: 10 min)

6. **[P3 #15, #16, #17, #18, #20] Minor cleanups** -- print-to-logger, stale comments, redundant raise, f-string logging. (Est: 30 min total)

7. **[P1 #2] Decompose `build_field_context_with_history()`** -- Extract helpers: `_build_input_source_namespace()`, `_build_context_source_namespace()`, `_handle_version_namespaces()`. (Est: 2-3 hours)

8. **[P2 #11] Unify the two `prepare_prompt_*` methods** -- Extract shared pipeline steps 4-7 into a private method. (Est: 1 hour)

9. **[P2 #10] Extract error-handling logic from `_render_prompt_template()`** -- Move `_collect_refs_with_namespace` to module level. (Est: 30 min)

10. **[P2 #8] Simplify renderer.py Strategy pattern** -- Inline `JinjaTemplateRenderer.render()` into `ConfigRenderingService`, remove unused ABCs and implementations. Requires verifying no external code injects alternative implementations. (Est: 2 hours)

11. **[P1 #1] Split `ContextScopeProcessor` into focused classes** -- This is the highest-impact but highest-effort change. Suggested split: `FieldReferenceParser` (parsing), `DependencyInferrer` (graph analysis), `FieldContextBuilder` (data loading), `ContextScopeApplier` (observe/drop/passthrough). Re-export from current location for backward compat. (Est: 1-2 days)

12. **[P2 #7] Evaluate field-reference system consolidation** -- Requires deeper analysis of whether `PromptUtils.parse_field_references` and `ContextScopeProcessor.parse_field_reference` can share a common parser. May not be worth the effort if usage contexts are sufficiently different. (Est: investigate 2 hours, implement 4 hours)
