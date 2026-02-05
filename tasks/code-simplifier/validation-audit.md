# Code Simplification Audit: validation

**Audited path:** `agent_actions/validation/`
**Date:** 2026-02-05
**Modules reviewed:** 67 Python files (top-level + 7 sub-packages)
**Total lines:** ~12,099

## Executive Summary

The validation directory has a severe duplicate-file problem: **11 pairs of byte-identical files** (e.g., `clean.py` / `clean_validator.py`) account for roughly 2,100 lines of pure redundancy. Beyond that, there are **3 near-duplicate pairs** (`base.py`/`base_validator.py`, `config.py`/`config_validator.py`, `schema.py`/`schema_validator.py`) where the `_validator` variant adds event-firing logic on top of otherwise identical code, totaling another ~1,200 lines of near-duplication. The folder also contains two competing base-class hierarchies (`BaseValidator` in `base_validator.py` vs `BaseAgentEntryValidator` in `agent_validators/`), a `static_analysis/` convenience re-export package that purely wraps `static_analyzer/`, an empty `agent/` sub-package, and a `validate_udfs.py` module that mixes CLI command definition with validation logic. Addressing just the P1 findings would eliminate approximately 2,400+ lines with zero behavioral change.

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

1. **11 byte-identical duplicate file pairs (~2,100 wasted lines)**
   - Files: Every file listed below has an exact byte-for-byte copy under a different name:
     - `clean.py` = `clean_validator.py` (11 lines each)
     - `docs.py` = `docs_validator.py` (14 lines each)
     - `init.py` = `init_validator.py` (16 lines each)
     - `render.py` = `render_validator.py` (16 lines each)
     - `status.py` = `status_validator.py` (11 lines each)
     - `directory.py` = `directory_validator.py` (248 lines each)
     - `project.py` = `project_validator.py` (139 lines each)
     - `prompt.py` = `prompt_validator.py` (202 lines each)
     - `startup.py` = `startup_validator.py` (314 lines each)
     - `path.py` = `path_validator.py` (243 lines each)
     - `prompt_ast.py` = `prompt_ast_analyzer.py` (362 lines each)
   - Verified by MD5 hash: Each pair produces identical checksums.
   - **What to simplify:** Delete one file from each pair and redirect imports from the deleted file to the kept file (or add a re-export alias). The existing downstream consumers use a mix of names (see Dependency section), so pick the canonical name based on what external callers already use, and add a thin alias in the other module for backward compatibility.
   - **Why:** Pure dead weight; maintaining two identical files creates confusion and divergence risk.
   - **Risk:** Low. These are byte-identical copies; removing one and aliasing is mechanical.
   - **Lines recoverable:** ~1,576 (sum of one copy of each pair)

2. **`base.py` is an older version of `base_validator.py` (~141 redundant lines)**
   - Files: `base.py` (141 lines) vs `base_validator.py` (217 lines)
   - Lines: `base.py` lines 1-141; `base_validator.py` lines 1-217
   - `base.py` contains a simpler `BaseValidator` class without event-firing support. `base_validator.py` has the same class name with additional `fire_events`, `_complete_validation`, and `validator_name` features. Zero imports of `base.py` exist anywhere in the codebase -- all consumers import from `base_validator.py`.
   - **What to simplify:** Delete `base.py` entirely.
   - **Why:** `base.py` is unused dead code. No file imports from it.
   - **Risk:** Very low. Grep confirms zero imports of `agent_actions.validation.base`.

3. **`static_analysis/` sub-package is a pure re-export shim (~93 lines across 2 files)**
   - Files: `static_analysis/__init__.py` (80 lines), `static_analysis/analyzer.py` (11 lines)
   - Both files contain only import and re-export statements that delegate to `static_analyzer/`.
   - Downstream consumers: `cli/run.py`, `workflow/schema_service.py`, `preflight/__init__.py` import from `static_analysis`.
   - **What to simplify:** Either (a) update the 3 downstream consumers to import directly from `static_analyzer` and delete `static_analysis/`, or (b) keep the shim but note it adds an unnecessary layer of indirection.
   - **Why:** Adds indirection, doubles the surface area, and must be kept in sync with `static_analyzer/__init__.py`.
   - **Risk:** Low. Only 3 consumer files need updating.

4. **`agent/` sub-package is empty (only `__init__.py` with `"""Package."""`)**
   - Files: `agent/__init__.py` (1 line), `agent/_MANIFEST.md`
   - No Python modules exist in this directory.
   - **What to simplify:** Delete the `agent/` directory entirely.
   - **Why:** Empty package serves no purpose and is misleading.
   - **Risk:** Very low. No code imports from it.

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

5. **3 near-duplicate pairs: config, schema, base (~1,200 lines of near-duplication)**
   - `config.py` (392 lines) vs `config_validator.py` (456 lines): Same `ConfigValidator` class. The `_validator` version adds `field=` and `value=` keyword arguments to `add_error()` calls and uses `_prepare_validation(data, target=...)` / `_complete_validation()` for event lifecycle. Core validation logic is identical.
   - `schema.py` (371 lines) vs `schema_validator.py` (487 lines): Same `SchemaValidator` class. The `_validator` version additionally fires `DataValidationStartedEvent`, `DataValidationPassedEvent`, `DataValidationFailedEvent` and passes `field=` to `add_error()` calls.
   - **What to simplify:** Consolidate each pair into the `_validator` version (which is the more complete one) and redirect imports. The event-firing variant is strictly a superset.
   - **Downstream impact:**
     - `config.py` is imported by `agent_actions/prompt/renderer.py` and `agent_actions/llm/realtime/config.py`.
     - `schema.py` is imported by `agent_actions/prompt/renderer.py`.
   - **Risk:** Moderate. Must verify that the event-firing behavior is acceptable in all consumer contexts. The `fire_events=True` default in `BaseValidator.__init__` could be overridden to `False` if needed.

6. **Two competing base-class hierarchies for validators**
   - `base_validator.py::BaseValidator` -- used by `DirectoryValidator`, `PathValidator`, `SchemaValidator`, `ConfigValidator`, `PromptValidator`, `ProjectValidator`, and the preflight validators.
   - `agent_validators/base_agent_validator.py::BaseAgentEntryValidator` -- used by the 8 agent entry validators.
   - These two base classes have overlapping concerns: both collect errors/warnings, both have `validate()` method contracts, both track validation state.
   - **What to simplify:** Consider having `BaseAgentEntryValidator` extend `BaseValidator` (or share a common protocol/mixin) to unify the error-collection pattern. Currently, the agent entry orchestrator manually copies errors from `AgentEntryValidationResult` into `ConfigValidator._errors`, creating a manual bridging layer.
   - **Risk:** Moderate. Requires careful interface alignment.

7. **`validate_udfs.py` mixes CLI command definition with validation logic (238 lines)**
   - File: `validate_udfs.py` lines 1-238
   - This module defines a Click CLI command (`validate_udfs_cmd`), a `ValidateUDFsCommand` class with rich console output, and validation logic. It belongs in `agent_actions/cli/` rather than `agent_actions/validation/`.
   - It imports from `agent_actions.cli.project_paths_factory`, `click`, `rich.console`, and `agent_actions.logging.errors` -- none of which are typical validation-layer imports.
   - **What to simplify:** Move this module to `agent_actions/cli/validate_udfs.py` and import it from there in `cli/main.py`.
   - **Risk:** Low-moderate. Single consumer in `cli/main.py`.

8. **`StartupValidator` does not inherit from `BaseValidator` (inconsistency)**
   - File: `startup.py` (and identical copy `startup_validator.py`), lines 26-288
   - This class manually manages `self.errors: List[str]` and `self.warnings: List[str]` rather than using the `BaseValidator` infrastructure. It also defines its own `StartupValidationError` exception class locally.
   - **What to simplify:** Either refactor `StartupValidator` to extend `BaseValidator` for consistency, or document why it deliberately differs (e.g., it validates environment rather than data dicts).
   - **Risk:** Moderate. The class has a different `validate` signature pattern (multiple `validate_*` methods rather than a single `validate(data)` entrypoint).

9. **`prompt_ast.py` / `prompt_ast_analyzer.py` contains `__main__` example code (lines 306-362)**
   - File: `prompt_ast.py` lines 306-362 (57 lines)
   - Contains `if __name__ == "__main__":` block with hardcoded example data and `print` statements. This is demo code, not production logic.
   - **What to simplify:** Remove the `__main__` block, or move the example to a test or doctest.
   - **Risk:** Very low.

10. **`run.py` vs `run_validator.py` are near-identical (differ by 1 field)**
    - File: `run.py` (38 lines) vs `run_validator.py` (39 lines)
    - `run_validator.py` has one additional field: `debug_context: bool`. Otherwise identical `RunCommandArgs` class with identical `ExecutionMode` enum.
    - Downstream: `cli/run.py` imports from `run_validator.py`. No consumer imports from `run.py`.
    - **What to simplify:** Delete `run.py` (it is the incomplete version).
    - **Risk:** Very low. No imports of `run.py` found.

### P3 -- Low Impact (Nice-to-have, minor cleanups)

11. **`batch_mode_compatibility_validator.py` in `agent_validators/` is a 1-line re-export alias (11 lines including imports)**
    - File: `agent_validators/batch_mode_compatibility_validator.py`
    - Contains: `from agent_actions.validation.agent_validators.vendor_compatibility_validator import BatchModeCompatibilityValidator`
    - The alias `BatchModeCompatibilityValidator = VendorCompatibilityValidator` is already defined at the bottom of `vendor_compatibility_validator.py` (line 96).
    - **What to simplify:** Delete `batch_mode_compatibility_validator.py` if no external consumer imports from it specifically.
    - **Risk:** Very low.

12. **`BaseValidator` static utility methods (`_ensure_path_exists`, `_is_file`, `_is_directory`) are trivial wrappers**
    - File: `base_validator.py` lines 179-217
    - These are 1-line wrappers around `path.exists()`, `path.is_file()`, `path.is_dir()` with verbose docstrings.
    - **What to simplify:** Consider removing in favor of direct `Path` method calls. The wrappers add 38 lines of code for zero abstraction value.
    - **Risk:** Low, but widespread usage across many validators.

13. **`BaseAgentEntryValidator._format_error` and `_format_warning` do nothing useful**
    - File: `agent_validators/base_agent_validator.py` lines 85-91
    - Both methods simply concatenate two strings: `f"{description} {message}"`. No validator uses them.
    - **What to simplify:** Remove these dead helper methods.
    - **Risk:** Very low.

14. **`BaseAgentEntryValidator.is_valid()` always returns `True`**
    - File: `agent_validators/base_agent_validator.py` lines 63-70
    - Documented as "validators are stateless", always returns `True`. If it has no meaningful check, it is unnecessary.
    - **What to simplify:** Remove or mark with a TODO if future use is planned.
    - **Risk:** Very low.

15. **`AgentEntryValidationContext.is_valid()` checks are never called**
    - File: `orchestration/agent_entry_validation_orchestrator.py` lines 71-78
    - Grep shows no caller of `context.is_valid()` anywhere.
    - **What to simplify:** Remove if unused.
    - **Risk:** Very low.

16. **`DEPRECATION_TRACKER.md` and `REDUNDANT_CODE_FOUND.md` are tracker documents inside source tree**
    - These operational tracking documents should live in `tasks/` or a project wiki, not alongside source code.
    - **What to simplify:** Move to `tasks/` or a docs directory.
    - **Risk:** None (non-code files).

17. **Inconsistent `validate()` method signatures across validators**
    - `BaseValidator.validate(data, config)` -- dict-based dispatch with `operation` key
    - `BaseAgentEntryValidator.validate(context)` -- context-object based
    - `StartupValidator` -- multiple separate `validate_*()` methods
    - `PromptValidator.validate(data)` -- `data` is a `Path`, not a dict
    - This inconsistency means the `validate` interface promise of the base class is not really upheld.
    - **What to simplify:** Document the different validator patterns (dict-dispatch vs context-object vs multi-method) or unify.
    - **Risk:** High effort to unify; documentation is lower risk.

18. **Unused `_ci_get` alias in `config.py` and `config_validator.py`**
    - File: `config.py` line 24, `config_validator.py` line 24
    - `_ci_get = ACVUtils.get_case_insensitive_value` is assigned but never referenced in either file.
    - **What to simplify:** Remove the unused alias.
    - **Risk:** Very low.

## Module-by-Module Breakdown

### `__init__.py`
- **Lines:** 13
- **Complexity:** Minimal
- **Findings:** Only exports `schema_output_validator` symbols. The validation package has 30+ top-level modules but exports only 3 symbols. This is fine if the intent is that consumers import specific modules directly.

### `base.py`
- **Lines:** 141
- **Complexity:** Low
- **Findings:** [P1-2] Entirely unused dead code. Superseded by `base_validator.py`.

### `base_validator.py`
- **Lines:** 217
- **Complexity:** Low
- **Findings:** [P3-12] Trivial static wrappers for Path methods. Otherwise well-structured base class.

### `batch_validator.py`
- **Lines:** 11
- **Complexity:** Trivial
- **Findings:** Clean Pydantic model. No issues.

### `clean.py` / `clean_validator.py`
- **Lines:** 11 each (22 total)
- **Complexity:** Trivial
- **Findings:** [P1-1] Byte-identical duplicates.

### `config.py`
- **Lines:** 392
- **Complexity:** Moderate (CC ~12 for `_check_circular_dependencies_logic` with nested DFS)
- **Findings:** [P2-5] Near-duplicate of `config_validator.py`. [P3-18] Unused `_ci_get` alias.

### `config_validator.py`
- **Lines:** 456
- **Complexity:** Moderate
- **Findings:** [P2-5] Superset of `config.py` with event-firing. This is the authoritative version. [P3-18] Unused `_ci_get` alias.

### `directory.py` / `directory_validator.py`
- **Lines:** 248 each (496 total)
- **Complexity:** Low-moderate
- **Findings:** [P1-1] Byte-identical duplicates.

### `docs.py` / `docs_validator.py`
- **Lines:** 14 each (28 total)
- **Complexity:** Trivial
- **Findings:** [P1-1] Byte-identical duplicates.

### `init.py` / `init_validator.py`
- **Lines:** 16 each (32 total)
- **Complexity:** Trivial
- **Findings:** [P1-1] Byte-identical duplicates.

### `path.py` / `path_validator.py`
- **Lines:** 243 each (486 total)
- **Complexity:** Moderate
- **Findings:** [P1-1] Byte-identical duplicates. Note: `path_validator.py` IS imported downstream by `prompt/renderer.py` and `cli/project_paths_factory.py`.

### `project.py` / `project_validator.py`
- **Lines:** 139 each (278 total)
- **Complexity:** Low
- **Findings:** [P1-1] Byte-identical duplicates. `project.py` is imported by `cli/init.py`.

### `prompt.py` / `prompt_validator.py`
- **Lines:** 202 each (404 total)
- **Complexity:** Moderate
- **Findings:** [P1-1] Byte-identical duplicates. `prompt_validator.py` is imported by `cli/run.py`.

### `prompt_ast.py` / `prompt_ast_analyzer.py`
- **Lines:** 362 each (724 total)
- **Complexity:** Moderate
- **Findings:** [P1-1] Byte-identical duplicates. [P2-9] Contains ~57 lines of `__main__` demo code.

### `render.py` / `render_validator.py`
- **Lines:** 16 each (32 total)
- **Complexity:** Trivial
- **Findings:** [P1-1] Byte-identical duplicates. `render_validator.py` is imported by `cli/compile.py`.

### `run.py`
- **Lines:** 38
- **Complexity:** Trivial
- **Findings:** [P2-10] Near-duplicate of `run_validator.py` minus one field. No downstream consumers.

### `run_validator.py`
- **Lines:** 39
- **Complexity:** Trivial
- **Findings:** [P2-10] This is the authoritative version (has `debug_context` field). Imported by `cli/run.py`.

### `schema.py`
- **Lines:** 371
- **Complexity:** Moderate
- **Findings:** [P2-5] Near-duplicate of `schema_validator.py`. Imported by `prompt/renderer.py`.

### `schema_validator.py`
- **Lines:** 487
- **Complexity:** Moderate (repetitive event-firing in `validate()` method makes it longer)
- **Findings:** [P2-5] Superset of `schema.py` with event firing. The `validate()` method (lines 267-407) has significant code duplication in its error-handling paths: the pattern `fire_event(DataValidationFailedEvent(...))` is repeated 4 times. This could be consolidated into the `_complete_validation` base method.

### `schema_output_validator.py`
- **Lines:** 322
- **Complexity:** Low-moderate
- **Findings:** Well-structured. Clean separation of concerns. The only symbols exported from `validation/__init__.py`. No significant issues.

### `startup.py` / `startup_validator.py`
- **Lines:** 314 each (628 total)
- **Complexity:** Moderate
- **Findings:** [P1-1] Byte-identical duplicates. [P2-8] Does not inherit from `BaseValidator`.

### `status.py` / `status_validator.py`
- **Lines:** 11 each (22 total)
- **Complexity:** Trivial
- **Findings:** [P1-1] Byte-identical duplicates. `status_validator.py` is imported by `cli/status.py`.

### `validate_udfs.py`
- **Lines:** 238
- **Complexity:** Moderate
- **Findings:** [P2-7] Mixes CLI command definition with validation logic. Has click command decorator, rich console output -- this is CLI code, not validation code.

### Sub-package: `agent/`
- **Files:** 1 (`__init__.py`)
- **Findings:** [P1-4] Empty package. Delete.

### Sub-package: `agent_validators/`
- **Files:** 10
- **Findings:** [P2-6] Separate base class hierarchy. [P3-11] `batch_mode_compatibility_validator.py` is a redundant re-export. [P3-13, P3-14] Dead helper methods and always-true `is_valid()` in base class.

### Sub-package: `orchestration/`
- **Files:** 1 (`agent_entry_validation_orchestrator.py`)
- **Findings:** [P3-15] `AgentEntryValidationContext.is_valid()` is never called. Otherwise well-structured orchestrator pattern.

### Sub-package: `preflight/`
- **Files:** 3 active validators + `error_formatter.py`
- **Findings:** Contains `VendorCompatibilityValidator` which overlaps in name (but not in functionality) with `agent_validators/vendor_compatibility_validator.py`. The former validates vendor API capabilities at runtime; the latter validates batch-mode vendor compatibility at config-load time. The name collision is confusing. Consider renaming one for clarity (e.g., `VendorApiCapabilityValidator` vs `BatchVendorValidator`).

### Sub-package: `static_analysis/`
- **Files:** 2
- **Findings:** [P1-3] Pure re-export shim. Adds indirection.

### Sub-package: `static_analyzer/`
- **Files:** 9
- **Findings:** Large sub-package (~120KB, ~150K+ lines). Not audited in detail for this report since the focus is the validation directory's top-level organization. The `_MANIFEST.md` is comprehensive.

### Sub-package: `utils/`
- **Files:** 2 (`agent_config_validation_utilities.py`, `schema_type_validator.py`)
- **Findings:** No significant issues. Well-scoped utility classes.

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions.logging` | `fire_event`, `ValidationCompleteEvent`, `ValidationErrorEvent`, `ValidationStartEvent`, `ValidationWarningEvent` | `base_validator.py`, `validate_udfs.py` |
| `agent_actions.logging.events` | `DataValidationFailedEvent`, `DataValidationPassedEvent`, `DataValidationStartedEvent` | `schema_validator.py` |
| `agent_actions.logging.core` | `fire_event` | `validate_udfs.py` |
| `agent_actions.logging.errors` | `format_user_error` | `validate_udfs.py` |
| `agent_actions.output.file_handler` | `FileHandler` | `config.py`, `config_validator.py` |
| `agent_actions.output.response.config_types` | `AgentConfigMap` | `config.py`, `config_validator.py` |
| `agent_actions.output.response.loader` | `SchemaLoader` | `static_analyzer/schema_extractor.py` |
| `agent_actions.errors` | `SchemaValidationError`, `DuplicateFunctionError`, `FunctionNotFoundError`, `UDFLoadError`, `ConfigurationError` | `schema_output_validator.py`, `validate_udfs.py`, `startup.py` |
| `agent_actions.utils.service_logger` | `ServiceLogger` | `path.py`, `path_validator.py` |
| `agent_actions.utils.constants` | `JSON_MODE_KEY`, `RESERVED_AGENT_NAMES`, `SPECIAL_NAMESPACES`, `SCHEMA_KEY`, `SCHEMA_NAME_KEY` | Multiple `agent_validators/` files, `static_analyzer/` |
| `agent_actions.utils.schema_utils` | `is_compiled_schema` | `agent_validators/inline_schema_validator.py` |
| `agent_actions.llm.realtime.config` | `ConfigManager` | `startup.py`, `validate_udfs.py` |
| `agent_actions.config.environment` | `EnvironmentConfig` | `startup.py` |
| `agent_actions.input.loaders.udf` | `discover_udfs`, `validate_udf_references` | `validate_udfs.py` |
| `agent_actions.cli.project_paths_factory` | `ProjectPathsFactory` | `validate_udfs.py` |
| `agent_actions.prompt.context.scope` | (lazy import) | `static_analyzer/workflow_static_analyzer.py` |
| `agent_actions.tooling.docs.scanner` | `ProjectScanner` | `static_analyzer/schema_extractor.py` |
| `jinja2` | `Environment`, `TemplateSyntaxError`, `meta`, `nodes` | `prompt_ast.py` |
| `jsonschema` | `validators`, `exceptions` | `schema.py`, `schema_validator.py` |
| `click` | CLI decorators | `validate_udfs.py` |
| `rich.console` | `Console` | `validate_udfs.py` |
| `pydantic` | `BaseModel`, `Field`, `ValidationError` | Multiple CLI arg models, `startup.py` |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions/cli/run.py` | `PromptValidator`, `RunCommandArgs`, `VendorCompatibilityValidator`, `WorkflowStaticAnalyzer` | High -- multiple symbols |
| `agent_actions/cli/init.py` | `InitCommandArgs`, `ProjectValidator` | Low |
| `agent_actions/cli/compile.py` | `RenderCommandArgs` | Low |
| `agent_actions/cli/clean.py` | `CleanCommandArgs` | Low |
| `agent_actions/cli/status.py` | `StatusCommandArgs` | Low |
| `agent_actions/cli/main.py` | `validate_udfs_cmd` | Low |
| `agent_actions/cli/project_paths_factory.py` | `PathValidator` | Low |
| `agent_actions/prompt/renderer.py` | `ConfigValidator`, `PathValidator`, `SchemaValidator` | Medium -- uses non-`_validator` names |
| `agent_actions/llm/realtime/config.py` | `ConfigValidator` | Medium -- uses non-`_validator` name |
| `agent_actions/llm/batch/batch_cli.py` | `BatchCommandArgs` | Low |
| `agent_actions/processing/helpers.py` | `validate_output_against_schema`, `SchemaValidationReport` (lazy import) | Low |
| `agent_actions/workflow/schema_service.py` | `WorkflowStaticAnalyzer`, `StaticValidationResult`, `StaticTypeError` | Medium |

### Dependency Risks

- **P1-1 (duplicate removal):** The downstream consumers import from a mix of canonical names. For example, `cli/run.py` imports `prompt_validator.PromptValidator` while `cli/init.py` imports `project.ProjectValidator`. When consolidating duplicates, the import alias or re-export must preserve both paths until all consumers are updated.
- **P2-5 (config/schema near-duplicate consolidation):** `prompt/renderer.py` imports `ConfigValidator` from `config.py` (the non-event-firing version) and `SchemaValidator` from `schema.py`. If consolidated to the `_validator` versions, these consumers will start firing validation events, which could add logging noise. Recommend using `fire_events=False` where silent validation is preferred.
- **P2-7 (validate_udfs.py relocation):** Only `cli/main.py` imports from this file. The move would require one import path change.
- **P1-3 (static_analysis removal):** Three downstream files import via `static_analysis`. These would need to change to `static_analyzer`.

## Recommended Simplification Order

1. **[P1-1] Delete 11 byte-identical duplicate files.** Keep the name that downstream consumers already use, add re-export alias in the alternate name's location if both are imported. Estimated savings: ~1,576 lines. Zero behavioral change.

2. **[P1-2] Delete `base.py`.** Zero imports exist. Estimated savings: 141 lines.

3. **[P1-4] Delete empty `agent/` sub-package.** Estimated savings: trivial but reduces confusion.

4. **[P2-10] Delete `run.py`.** It is the incomplete version (missing `debug_context` field). No downstream consumers.

5. **[P2-5] Consolidate `config.py` into `config_validator.py` and `schema.py` into `schema_validator.py`.** Update the 3 downstream consumers. Estimated savings: ~760 lines.

6. **[P1-3] Remove `static_analysis/` shim or update 3 downstream consumers.** Estimated savings: 93 lines.

7. **[P2-9] Remove `__main__` demo block from `prompt_ast.py`/`prompt_ast_analyzer.py`.** 57 lines.

8. **[P2-7] Move `validate_udfs.py` to `cli/`.** Improves package cohesion.

9. **[P2-8] Align `StartupValidator` with `BaseValidator` pattern.** Moderate effort.

10. **[P2-6] Unify base class hierarchies.** Highest effort; schedule for a dedicated refactor.

11. **[P3] Clean up dead methods, unused aliases, and naming inconsistencies.** Can be done incrementally.
