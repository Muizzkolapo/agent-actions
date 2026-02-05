# Code Simplification Audit: output

**Audited path:** `agent_actions/output/`
**Date:** 2026-02-05
**Modules reviewed:** 13 (4 top-level + 9 in `response/` sub-package)

## Executive Summary

The `output/` folder contains 2,926 lines across 12 modules spanning two concerns: file I/O operations (`file_handler.py`, `writer.py`, `saver.py`) and response/config processing (`response/` sub-package). The most significant simplification opportunities are: (1) four near-identical `dangerous_patterns` lists duplicated across three files that should be extracted into a single shared constant, (2) three `FileHandler` static methods that appear to be dead code with no callers outside the class itself, and (3) a repetitive error-handling pattern in `writer.py` where three write methods share an almost identical try/except structure. The folder is generally well-structured, but the `response/` sub-package has grown into a configuration expansion module that has outgrown its name.

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

1. **Quadruplicated `dangerous_patterns` lists across `guard_parser.py` and `config_schema.py`**
   - **Files:** `response/guard_parser.py` (lines 127-146, 180-198), `response/config_schema.py` (lines 68-86, 144-157)
   - **What:** Four separate inline definitions of nearly identical dangerous pattern blocklists. The lists in `guard_parser.py` have 17 and 18 entries respectively (the UDF variant adds `"__"`), while the two in `config_schema.py` have 16 and 12 entries. The differences between the four lists appear unintentional -- some include `dir`/`hasattr`/`getattr`/`setattr`/`delattr` and others do not.
   - **Why:** This is a maintenance hazard. If a new dangerous pattern needs to be added (or one removed), all four locations must be found and updated in sync. The inconsistencies between the lists suggest this has already happened.
   - **Recommendation:** Extract a single `DANGEROUS_PATTERNS` constant (and optionally a `DANGEROUS_PATTERNS_STRICT` superset for UDF) into a shared location (e.g., `agent_actions/utils/constants.py` or a new `agent_actions/output/response/security.py`), and a reusable `validate_no_dangerous_patterns(expression, context)` helper.
   - **Risk:** Low. Pure refactor with no behavioral change.

2. **Dead code in `FileHandler`: `find_agent_folder`, `get_folder`, `get_file_info`**
   - **File:** `file_handler.py` (lines 55-71, 139-152, 173-194)
   - **What:** Three static methods -- `find_agent_folder`, `get_folder`, and `get_file_info` -- have zero external callers anywhere in the codebase (confirmed by grep). `get_folder` calls `find_config_file` and `get_folder_after_agent_config` internally, but it is never called itself.
   - **Why:** Dead code increases surface area, confuses readers about what the API actually is, and adds maintenance burden. These methods total ~45 lines.
   - **Recommendation:** Remove these three methods. If they are needed in the future they can be recovered from git history.
   - **Risk:** Low. No callers exist. Tests should be run to confirm nothing uses them via dynamic dispatch.

3. **Repetitive try/except boilerplate in `FileWriter.write_staging`, `write_target`, `write_source`**
   - **File:** `writer.py` (lines 55-111, 113-169, 171-210)
   - **What:** All three methods follow the exact same pattern: fire `FileWriteStartedEvent` -> do work -> compute `bytes_written` -> fire `FileWriteCompleteEvent` -> catch `IOError` -> call `handle_file_error` -> catch `Exception` -> call `handle_processing_error`. The event-firing and error-handling code is copied verbatim across all three methods (~18 lines per method, ~54 lines total).
   - **Why:** Any change to the event-fire or error-handling pattern must be replicated three times. The duplication obscures the meaningful differences between the methods (the actual write logic).
   - **Recommendation:** Extract a private `_write_with_events(self, operation_name, write_fn)` method that handles the event/error lifecycle, and have each public method supply only the write lambda.
   - **Risk:** Low. Internal refactor with stable external API.

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

4. **`SourceSaveMode` enum and `get_source_data_saver` factory produce identical objects**
   - **File:** `saver.py` (lines 23-28, 146-186)
   - **What:** `SourceSaveMode` has two values (`BATCH` and `ONLINE`), and `get_source_data_saver` constructs a `UnifiedSourceDataSaver` for each. The only difference is `enable_locking=True` vs `enable_locking=False`. But `enable_locking` is explicitly documented as deprecated and ignored (line 44, 53, 63). Both modes also set `enable_deduplication=True`. This means both code paths produce functionally identical objects.
   - **Why:** The mode enum, the factory function, and the `enable_locking` parameter are all vestigial. They add 40+ lines of code that do nothing and mislead readers into thinking there is meaningful behavioral divergence between batch and online saving.
   - **Recommendation:** Remove `SourceSaveMode`, `get_source_data_saver`, and the `enable_locking` parameter. Callers should construct `UnifiedSourceDataSaver` directly. Check that the one external caller (`initial_pipeline.py` line 125) does not depend on the locking parameter.
   - **Risk:** Moderate. The factory function is in `__all__` and callers in `initial_pipeline.py` use `enable_locking=True`. Requires coordinated update of one call site.

5. **`AgentEntryDict` (TypedDict) and `AgentConfig` (Pydantic model) define overlapping field sets**
   - **Files:** `response/config_types.py` (lines 6-33), `response/config_schema.py` (lines 196-253)
   - **What:** `AgentEntryDict` is a `TypedDict` with 17 fields. `AgentConfig` is a Pydantic `BaseModel` with 25+ fields. They share at least 14 field names (`agent_type`, `name`, `model_name`, `model_vendor`, `api_key`, `code_path`, `dependencies`, `prompt`, `schema_name`, `chunk_config`, `is_operational`, `conditional_clause`, `where_clause`, `skip_if`, `ephemeral`, `add_dispatch`, `anthropic_version`, `enable_prompt_caching`, `context_scope`). The two definitions can drift independently -- for example, `AgentConfig` has `json_mode`, `prompt_debug`, `max_execution_time`, `enable_caching` fields that `AgentEntryDict` lacks.
   - **Why:** Having two parallel definitions of "agent config shape" is a consistency hazard. Changes to one are not automatically reflected in the other. The TypedDict is used at runtime (as a plain dict), while the Pydantic model is used for validation. They serve different purposes but the field drift makes the contract unclear.
   - **Recommendation:** Consider deriving `AgentEntryDict` from the Pydantic model's field list, or replacing `AgentEntryDict` usage with `AgentConfig` validation at boundaries. At minimum, add a cross-reference comment in both files.
   - **Risk:** Moderate. The TypedDict is used extensively in `expander.py`, `renderer.py`, `data_generator.py`, and `base.py`. A full unification would touch multiple folders.

6. **`ActionExpander` is a class with zero instance state -- all methods are `@staticmethod`**
   - **File:** `response/expander.py` (lines 26-614)
   - **What:** `ActionExpander` has 16 methods, all marked `@staticmethod`. The constructor (line 33-35) does nothing. No instance is ever created with meaningful state.
   - **Why:** Using a class as a namespace for static methods is a Python anti-pattern. It forces `ActionExpander._method_name(...)` at every internal call instead of simple function calls. It also makes testing more verbose (must reference `ActionExpander.method` rather than importing a function).
   - **Recommendation:** Convert to module-level functions with a leading underscore convention for private helpers. Export `expand_actions_to_agents` and `validate_guard_references` directly. This is a larger refactor but straightforward.
   - **Risk:** Moderate. `ActionExpander` is imported by 6 test files and 1 production module (`llm/realtime/config.py`). All call `ActionExpander.expand_actions_to_agents(...)` or `ActionExpander.validate_guard_references(...)`.

7. **`FileHandler` is also an all-static-methods class with no instance state**
   - **File:** `file_handler.py` (lines 12-194)
   - **What:** All 9 methods are `@staticmethod`. The class is used purely as a namespace.
   - **Why:** Same anti-pattern as finding #6. Forces `FileHandler.method_name()` syntax with no benefit.
   - **Recommendation:** Convert to module-level functions. Less urgent than `ActionExpander` since `FileHandler` is smaller and more stable.
   - **Risk:** Moderate. `FileHandler` is imported by 8 external modules.

### P3 -- Low Impact (Nice-to-have, minor cleanups)

8. **Stale comment in `writer.py` line 10**
   - **File:** `writer.py` (line 10)
   - **What:** `from agent_actions.errors import AgentActionsException  # New modular pattern!`
   - **Why:** The "New modular pattern!" comment is a development-time annotation that should have been removed. It conveys no useful information to a reader.
   - **Risk:** Trivial.

9. **`response/__init__.py` is empty**
   - **File:** `response/__init__.py` (0 lines)
   - **What:** The file exists but contains no content -- no `__all__`, no re-exports.
   - **Why:** While an empty `__init__.py` is valid, all consumers import directly from submodules (e.g., `from agent_actions.output.response.expander import ActionExpander`). If this is intentional, a brief comment clarifying the design choice would aid readability. Alternatively, re-export the public API to simplify import paths.
   - **Risk:** Trivial.

10. **`print()` call in `FileHandler.find_config_file` (line 111)**
    - **File:** `file_handler.py` (line 111)
    - **What:** `print(f"Config file '{filename}' not found...")` -- uses `print()` instead of `logger.warning()` or `logger.error()`.
    - **Why:** The rest of the codebase uses the `logging` module consistently. A `print()` call is invisible to log configuration, cannot be filtered, and does not include timestamps or log levels.
    - **Risk:** Trivial.

11. **`SchemaLoader` class (all-static, same pattern as findings #6 and #7)**
    - **File:** `response/loader.py` (lines 28-285)
    - **What:** Another all-static-method class with no instance state.
    - **Why:** Same namespace-as-class anti-pattern.
    - **Risk:** Trivial refactor but `SchemaLoader` is imported by 5 external modules.

12. **`GuardParser.parse_consolidated` creates a circular dependency import**
    - **File:** `response/guard_parser.py` (lines 232-245)
    - **What:** `parse_consolidated` does a local import of `parse_guard_config` from `consolidated_guard.py`, which itself imports from `guard_parser.py` at module level. The `# pyright: reportImportCycles=false` suppress in `consolidated_guard.py` (line 2) confirms this is a known cycle.
    - **Why:** The method is a thin wrapper: `return parse_guard_config(guard_data)`. The convenience adds indirection without adding value. Callers could import `parse_guard_config` directly.
    - **Recommendation:** Remove `GuardParser.parse_consolidated` and have the 5 test call sites import `parse_guard_config` from `consolidated_guard` directly.
    - **Risk:** Low. Only tests call this method.

13. **`_process_schema_config` has dead branch at line 187**
    - **File:** `response/expander.py` (lines 182-187)
    - **What:** Lines 184-185 handle `isinstance(schema_value, str)` and lines 186-187 handle `isinstance(schema_value, dict)`, then line 187 has an `else` clause that does `agent["schema"] = schema_value` -- identical to the dict branch on line 185. The else branch handles non-str, non-dict values by assigning them directly, which is functionally equivalent to the dict branch.
    - **Why:** The duplicated assignment suggests a copy-paste oversight or an incomplete type narrowing.
    - **Risk:** Trivial.

14. **Docstring in `saver.py` references JSON file fallback that no longer exists**
    - **File:** `saver.py` (lines 69-74, 82-83)
    - **What:** The docstring for `save_source_items` still describes step 3 "Load existing items (if file exists)" and step 5 "Merge and save", and mentions "If a storage_backend is configured, writes to the backend instead." But the method now unconditionally requires a storage backend and raises `ValueError` without it (lines 122-127). The docstring implies optional behavior that no longer exists.
    - **Why:** Stale docstrings mislead readers about the contract.
    - **Risk:** Trivial.

15. **`construct_schema_from_dict` field-type parsing is deeply nested**
    - **File:** `response/loader.py` (lines 179-240)
    - **What:** The method has 4 levels of nesting: `for` -> `if is_required` -> `if startswith("array[")` -> `if startswith("object:")`. The inner branches handle array-of-object, array-of-primitive, plain array, and scalar types.
    - **Why:** While the total line count is manageable (~50 lines), the nesting depth makes the control flow harder to follow. Extracting the inner type-parsing logic into a `_parse_field_type(field_name, field_type) -> dict` helper would flatten it.
    - **Risk:** Trivial.

## Module-by-Module Breakdown

### `__init__.py`
- **Lines:** 11
- **Complexity:** Minimal
- **Findings:** None. Clean re-export of `FileHandler` and `FileWriter`.

### `file_handler.py`
- **Lines:** 194
- **Complexity:** Low per-method, but 9 methods in total
- **Findings:**
  - P1 #2: Three dead methods (`find_agent_folder`, `get_folder`, `get_file_info`)
  - P2 #7: All-static-method class anti-pattern
  - P3 #10: `print()` instead of `logger`

### `saver.py`
- **Lines:** 186
- **Complexity:** Low
- **Findings:**
  - P2 #4: `SourceSaveMode` and `get_source_data_saver` are vestigial
  - P3 #14: Stale docstring referencing removed JSON fallback

### `writer.py`
- **Lines:** 210
- **Complexity:** Low per-method, but repetitive structure
- **Findings:**
  - P1 #3: Repetitive try/except/event boilerplate across three write methods
  - P3 #8: Stale "New modular pattern!" comment

### `response/__init__.py`
- **Lines:** 0
- **Complexity:** N/A
- **Findings:**
  - P3 #9: Empty file with no re-exports

### `response/config_fields.py`
- **Lines:** 83
- **Complexity:** Low
- **Findings:** None. Clean, well-documented module.

### `response/config_schema.py`
- **Lines:** 262
- **Complexity:** Moderate (validation logic with multiple branches)
- **Findings:**
  - P1 #1: Two duplicated `dangerous_patterns` lists (lines 68-86 and 144-157)
  - P2 #5: Overlapping field definitions with `config_types.py`

### `response/config_types.py`
- **Lines:** 39
- **Complexity:** Minimal
- **Findings:**
  - P2 #5: Overlapping field definitions with `config_schema.py`

### `response/consolidated_guard.py`
- **Lines:** 126
- **Complexity:** Low
- **Findings:**
  - P3 #12: Participates in circular import with `guard_parser.py`

### `response/expander.py`
- **Lines:** 760
- **Complexity:** High -- largest module in the folder, 16 methods, deep call chains
- **Findings:**
  - P2 #6: All-static-method class anti-pattern
  - P3 #13: Dead/duplicate branch in `_process_schema_config`

### `response/guard_parser.py`
- **Lines:** 253
- **Complexity:** Moderate (regex validation, error reporting)
- **Findings:**
  - P1 #1: Two duplicated `dangerous_patterns` lists (lines 127-146 and 180-198)
  - P3 #12: Participates in circular import with `consolidated_guard.py`

### `response/loader.py`
- **Lines:** 285
- **Complexity:** Moderate (schema loading with file I/O and YAML parsing)
- **Findings:**
  - P3 #11: All-static-method class anti-pattern
  - P3 #15: Deeply nested field-type parsing in `construct_schema_from_dict`

### `response/schema.py`
- **Lines:** 517
- **Complexity:** Moderate (schema compilation for multiple vendors)
- **Findings:** Well-decomposed into small private helper functions. No major findings.

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions/errors` | `AgentActionsException`, `ValidationError`, `ConfigValidationError`, `ConfigurationError`, `SchemaValidationError` | `writer.py`, `config_schema.py`, `guard_parser.py`, `expander.py`, `loader.py`, `schema.py`, `consolidated_guard.py` |
| `agent_actions/processing` | `ProcessorErrorHandlerMixin` | `writer.py` |
| `agent_actions/logging` | `fire_event`, `LoggerFactory`, event classes | `writer.py`, `saver.py`, `loader.py` |
| `agent_actions/llm/config` | `VendorType` | `expander.py` |
| `agent_actions/utils` | `RESERVED_AGENT_NAMES`, `SCHEMA_KEY`, `SCHEMA_NAME_KEY`, `is_compiled_schema`, `get_udf_metadata` | `expander.py`, `schema.py` |
| `agent_actions/input/preprocessing` | `ReferenceValidator`, `ReferenceParser` | `expander.py` |
| `agent_actions/prompt` | `PromptUtils`, `render_pipeline_with_templates` | `schema.py`, `loader.py` |
| `agent_actions/storage` (TYPE_CHECKING only) | `StorageBackend` | `writer.py`, `saver.py` |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions/llm/realtime` | `FileWriter`, `FileHandler`, `AgentConfig`, `DefaultAgentConfig`, `ActionExpander`, `prepare_schema_unified` | **High** -- 4 modules depend on this folder's core types and functions |
| `agent_actions/llm/batch` | `FileWriter`, `UnifiedSourceDataSaver`, `prepare_schema_unified`, `compile_unified_schema` | **High** -- batch processing depends on writer and schema compilation |
| `agent_actions/prompt` | `FileHandler`, `AgentEntryDict`, `AgentConfigMap`, `AgentConfig` | **High** -- renderer and handler depend on config types |
| `agent_actions/validation` | `FileHandler`, `AgentConfigMap` | Medium -- validators use file handler and config types |
| `agent_actions/input` | `FileWriter`, `UnifiedSourceDataSaver`, `AgentEntryDict` | Medium -- preprocessing and loaders depend on output types |
| `agent_actions/cli` | `FileHandler`, `SchemaLoader` | Low -- CLI tooling, less critical path |
| `agent_actions/tooling/docs` | `SchemaLoader` | Low -- docs generation |
| `agent_actions/config` | `GuardParser`, `parse_guard_config` | Low -- config schema validation |
| `tests/` | `ActionExpander`, `GuardParser`, `GuardConfig`, `FileWriter`, `WhereClauseConfig`, etc. | N/A -- test code |

### Dependency Risks

- **Finding P1 #1 (dangerous_patterns extraction):** Zero downstream risk. The lists are internal to validation logic; extracting them to a shared constant changes no external interface.
- **Finding P1 #2 (dead code removal):** Zero downstream risk. No external callers exist for the three methods.
- **Finding P1 #3 (writer boilerplate):** Zero downstream risk. The public API (`write_staging`, `write_target`, `write_source`) remains unchanged.
- **Finding P2 #4 (remove SourceSaveMode/factory):** Requires updating `agent_actions/input/preprocessing/staging/initial_pipeline.py` (1 call site). Low risk.
- **Finding P2 #5 (config type unification):** **High blast radius.** `AgentEntryDict` is consumed by `prompt/renderer.py`, `prompt/data_generator.py`, `input/loaders/base.py`, `validation/config_validator.py`, `validation/config.py`, and heavily throughout `expander.py`. Any structural change to config types must be coordinated across all these consumers.
- **Finding P2 #6 (ActionExpander to functions):** Requires updating `llm/realtime/config.py` and 6 test files. Medium blast radius.
- **Finding P2 #7 (FileHandler to functions):** Requires updating 8 consumer modules. Medium blast radius.

## Recommended Simplification Order

1. **P1 #1 -- Extract `dangerous_patterns` into shared constant.** Highest ratio of maintenance-risk-reduction to effort. Purely internal, zero external API impact. Start here.
2. **P1 #2 -- Remove dead `FileHandler` methods.** Quick win: delete ~45 lines of unused code with no callers. Run tests to confirm.
3. **P1 #3 -- Extract writer event/error boilerplate.** Internal refactor that removes ~36 lines of duplication and makes the write methods easier to read.
4. **P3 #8 and #10 -- Fix stale comment and print() call.** Trivial fixes that can be bundled into any nearby commit.
5. **P3 #14 -- Update stale docstring in `saver.py`.** Trivial but prevents future confusion.
6. **P2 #4 -- Remove vestigial `SourceSaveMode` and factory.** One external call site to update. Good cleanup after the easy wins.
7. **P3 #12 -- Remove `GuardParser.parse_consolidated` to break circular import.** Low-effort removal of a thin wrapper. Only test code needs updating.
8. **P2 #6 -- Convert `ActionExpander` to module-level functions.** Larger refactor but straightforward. Improves readability of the largest module in the folder.
9. **P2 #7 -- Convert `FileHandler` to module-level functions.** Similar to #8 but with more downstream consumers.
10. **P2 #5 -- Unify `AgentEntryDict` and `AgentConfig` field definitions.** Highest effort, highest blast radius. Should be tackled only after the simpler items are done and with a clear migration plan.
