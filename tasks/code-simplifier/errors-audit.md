# Code Simplification Audit: errors

**Audited path:** `agent_actions/errors/`
**Date:** 2026-02-05
**Modules reviewed:** 12 (including `__init__.py`)

## Executive Summary

The errors folder is a well-organized exception hierarchy with a clean base class pattern, but contains one critical duplicate file (`external.py` is byte-for-byte identical to `external_services.py`), a latent runtime bug (`ContextStructureError` referenced but never defined), several unused exception classes, stale backward-compatibility aliases still actively consumed, and a stale manifest listing phantom classes. Simplification effort is low-to-moderate, with the highest-value items being the duplicate file removal and fixing the missing class definition.

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

1. ~~**Duplicate file: `external.py` is identical to `external_services.py`**~~ **DONE** (PR #902)
   - **File:** `agent_actions/errors/external.py` (93 lines) and `agent_actions/errors/external_services.py` (93 lines)
   - **What:** These two files are byte-for-byte identical. `diff` produces zero output. The `__init__.py` imports from `external_services.py` only. No other file in the codebase imports from `external.py`.
   - **Why simplify:** Dead file that creates confusion about which is canonical, doubles maintenance surface, and could lead to divergent edits.
   - **Risk:** None. `external.py` has zero downstream consumers.

2. ~~**Missing class definition: `ContextStructureError` referenced but never defined**~~ **DONE** (PR #902)
   - **File:** Referenced in `agent_actions/prompt/service.py` lines 333-341 as `from agent_actions.errors.preflight import ContextStructureError`
   - **What:** `ContextStructureError` does not exist as a class definition in `preflight.py` or anywhere else in the codebase. The manifest (`_MANIFEST.md` line 43) lists it as a class in `preflight.py`, but it was never implemented. At runtime, if `request.agent_config is None` in `prompt/service.py`, the lazy import will raise `ImportError`.
   - **Why simplify:** This is a latent runtime bug. Either define the class in `preflight.py` or replace the reference with an existing error class (e.g., `PreFlightValidationError`).
   - **Risk:** Low -- the fix is straightforward, but the code path may be rarely triggered.

3. ~~**Stale manifest: `DependencyValidationError` listed but not defined in errors folder**~~ **DONE** (PR #902)
   - **File:** `agent_actions/errors/_MANIFEST.md` line 44
   - **What:** The manifest lists `DependencyValidationError` as a class in `preflight.py`, but it does not exist there. A separate `DependencyValidationError` exists in `agent_actions/input/preprocessing/field_resolution/exceptions.py` (inheriting from `FieldResolutionError`, not from the errors hierarchy). The manifest is misleading.
   - **Why simplify:** Stale manifest entries cause navigation errors for developers and AI agents relying on AMP.
   - **Risk:** None -- manifest-only change.

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

4. ~~**Backward-compatibility aliases still actively consumed**~~ **PARTIALLY DONE** (PR #902)
   - **File:** `agent_actions/errors/__init__.py` lines 82-86
   - **What:** Five aliases were defined. PR #902 removed three (`LoaderError`, `UnsupportedFormatError`, `DataParseError`) and migrated `DataParseError` call sites in `json.py`/`xml.py` to `ValidationError`.
   - **Remaining:**
     - `AgentActionsException = AgentActionsError` -- **heavily used** (20+ call sites) -- dedicated PR needed
     - `ProcessorError = ProcessingError` -- **used** in `processing/error_handling.py`
   - **Risk:** Moderate -- remaining aliases require coordinated changes across many files.

5. ~~**`TemplateVariableError` bypasses base class `context`/`cause` contract**~~ **DONE** (PR #902)
   - **File:** `agent_actions/errors/operations.py` lines 25-59
   - **What:** `TemplateVariableError.__init__` stored `self.cause = cause` directly and called `super().__init__(msg)` without `context=` or `cause=`. Now delegates properly, and args are keyword-only to match the rest of the hierarchy.
   - **Risk:** Low -- callers already rely on the instance attributes directly.

6. **`VendorAPIError` multi-signature `__init__` is overly complex**
   - **File:** `agent_actions/errors/external_services.py` lines 15-63
   - **What:** The constructor accepts `message_or_vendor` (dual-purpose first positional arg), `endpoint`, `**kwargs` for a `vendor` keyword, and has three code paths. This "supports two signatures" pattern adds 48 lines of branching logic to disambiguate calling conventions. The `**kwargs` for `vendor` is particularly unusual.
   - **Why simplify:** Hard to understand, error-prone, and not clearly documented which callers use which style. A clean break (deprecate old style, use explicit keyword-only params) would remove the ambiguity.
   - **Risk:** Moderate -- requires auditing all `VendorAPIError` call sites to determine which signature they use.

7. **`ConfigValidationError` multi-signature `__init__` complexity**
   - **File:** `agent_actions/errors/configuration.py` lines 14-54
   - **What:** Three calling conventions ("new style", "old keyword", "old positional") with branching logic to detect which is being used. The `message` parameter doubles as `config_key` in the old positional style.
   - **Why simplify:** Same reasoning as finding #6. Dual-purpose parameters are a maintenance hazard.
   - **Risk:** Moderate -- requires auditing call sites.

8. **Duplicated `format_user_message` pattern across `SchemaValidationError` and `PreFlightValidationError`**
   - **File:** `agent_actions/errors/validation.py` lines 114-156 and `agent_actions/errors/preflight.py` lines 63-94
   - **What:** Both classes override `__str__` to call `self.format_user_message()`, and both implement nearly identical formatting logic: build a list of lines from the message, add optional sections (missing fields/references, available references, hints), and join with newlines. The pattern is the same; only the specific attributes differ.
   - **Why simplify:** Extracting a shared `format_user_message` mixin or base method would eliminate ~60 lines of duplicated formatting logic.
   - **Risk:** Low.

### P3 -- Low Impact (Nice-to-have, minor cleanups)

9. **Unused exception classes: `SerializationError`, `EnvironmentConfigError`, `ResourceMemoryError`, `InvalidParameterError`**
   - **Files:**
     - `SerializationError` in `processing.py` line 31 -- defined and exported, never raised or caught outside the errors module
     - `EnvironmentConfigError` in `configuration.py` line 134 -- defined and exported, never raised or caught outside the errors module
     - `ResourceMemoryError` in `resources.py` line 13 -- defined and exported, never raised or caught outside the errors module
     - `InvalidParameterError` in `common.py` line 10 -- defined and exported, never raised or caught outside the errors module
   - **Why simplify:** Dead code. These classes exist only as definitions with no consumers. They may be intended for future use, but currently they just add noise.
   - **Risk:** Low -- removing them could break third-party code that imports them, but they are internal exceptions unlikely to have external consumers. Consider deprecation warnings first.

10. **`pass` statements in empty exception class bodies**
    - **Files:** `common.py` line 16, `configuration.py` lines 11/95/125/131/137, `external_services.py` lines 12/69/75/81/87/93, `filesystem.py` lines 10/16/22/28, `operations.py` lines 10/16/22, `processing.py` lines 10/16/22/28/34, `resources.py` lines 10/22/26, `validation.py` lines 12/18/24
    - **What:** All simple exception subclasses use `pass` in the body. This is standard Python but the codebase has suppression comments (`# Unnecessary-pass: ...`) at the top of every file, suggesting a linter flag. The Pythonic alternative is to use a docstring-only body (which these classes already have).
    - **Why simplify:** Remove the `pass` statements since the classes already have docstrings (which serve as the body). Remove the suppression comments. Minor but reduces noise by ~30 `pass` lines and ~10 suppression comments.
    - **Risk:** None.

11. **Suppression comments at module level are cargo-culted**
    - **Files:** Most modules have comments like `# Too-many-arguments: Legacy compatibility...` or `# Unnecessary-pass: Simple exception classes...`
    - **What:** These look like they were added to suppress linter warnings, but they are plain comments (not proper `# noqa` or `# type: ignore` directives). They do not actually suppress anything in ruff or pylint. They are documentation comments disguised as suppression directives.
    - **Why simplify:** If they serve as documentation, they should say so clearly. If they are meant to suppress linting, they need to use the proper syntax.
    - **Risk:** None.

12. **Unused typing imports in `validation.py`**
    - **File:** `agent_actions/errors/validation.py` line 4
    - **What:** `from typing import Any, Dict, List, Optional, Tuple` -- `List` and `Tuple` are used, but this could be verified. All five imports appear to be used in `SchemaValidationError.__init__` signature.
    - **Why simplify:** After inspection, all imports appear used. No action needed. (Included for completeness of the audit.)
    - **Risk:** N/A.

## Module-by-Module Breakdown

### `__init__.py`
- **Lines:** 145
- **Complexity:** Low -- purely re-exports and aliases
- **Findings:**
  - [P1-3] Manifest lists phantom classes not present in actual exports
  - [P2-4] Five backward-compatibility aliases, two of which are unused (`LoaderError`, `UnsupportedFormatError`)

### `base.py`
- **Lines:** 62
- **Complexity:** Low -- clean base class with context dict and cause chaining
- **Findings:**
  - Lazy import of `format_exception_context` from `agent_actions.utils.safe_format` inside `__str__` is a defensive pattern to avoid circular imports. Acceptable but worth noting as an upstream dependency.
  - No simplification needed.

### `common.py`
- **Lines:** 16
- **Complexity:** Minimal -- single exception class
- **Findings:**
  - [P3-9] `InvalidParameterError` is defined but never raised or caught anywhere in the codebase
  - [P3-10] Unnecessary `pass` statement

### `configuration.py`
- **Lines:** 137
- **Complexity:** Medium -- `ConfigValidationError` and `DuplicateFunctionError` have complex multi-signature constructors
- **Findings:**
  - [P2-7] `ConfigValidationError` has 3 calling conventions with branching disambiguation
  - `DuplicateFunctionError` similarly has dual calling conventions (lines 60-89)
  - [P3-9] `EnvironmentConfigError` is never used outside the errors module
  - [P3-10] Multiple `pass` statements in simple subclasses

### `external.py`
- **Lines:** 93
- **Complexity:** N/A -- dead duplicate
- **Findings:**
  - [P1-1] Byte-for-byte duplicate of `external_services.py`. Zero imports. Should be deleted.

### `external_services.py`
- **Lines:** 93
- **Complexity:** Medium -- `VendorAPIError` multi-signature constructor
- **Findings:**
  - [P2-6] `VendorAPIError.__init__` has 3 code paths and uses `**kwargs` for a `vendor` keyword argument

### `filesystem.py`
- **Lines:** 28
- **Complexity:** Minimal -- four simple exception classes
- **Findings:**
  - [P3-10] `pass` statements in all classes
  - Clean and well-structured

### `operations.py`
- **Lines:** 59
- **Complexity:** Medium -- `TemplateVariableError` has custom `__init__` that bypasses base class contract
- **Findings:**
  - [P2-5] `TemplateVariableError` does not pass `context` or `cause` to parent `__init__`
  - The class stores `self.cause` directly, shadowing the pattern where `AgentActionsError.__init__` sets `__cause__`

### `preflight.py`
- **Lines:** 196
- **Complexity:** Medium -- `PreFlightValidationError` has the most parameters (8 keyword args)
- **Findings:**
  - [P1-2] `ContextStructureError` referenced in manifest and in `prompt/service.py` but never defined -- latent `ImportError`
  - [P1-3] `DependencyValidationError` listed in manifest but not defined
  - [P2-8] `format_user_message` duplicates pattern from `SchemaValidationError`
  - Well-designed otherwise; clean use of keyword-only params

### `processing.py`
- **Lines:** 34
- **Complexity:** Minimal -- five simple exception classes
- **Findings:**
  - [P3-9] `SerializationError` is never used
  - [P3-10] `pass` statements

### `resources.py`
- **Lines:** 26
- **Complexity:** Minimal -- three simple exception classes
- **Findings:**
  - [P3-9] `ResourceMemoryError` is never used
  - Good naming note: avoids shadowing Python's built-in `MemoryError`

### `validation.py`
- **Lines:** 156
- **Complexity:** Medium -- `SchemaValidationError` has 14 keyword parameters
- **Findings:**
  - [P2-8] `format_user_message` duplicates pattern with `PreFlightValidationError`
  - The 14-parameter constructor is justified by its structured diagnostic purpose
  - Clean separation of context-building and instance-attribute storage

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions/utils/safe_format.py` | `format_exception_context` | `base.py` (lazy import in `__str__`) |

This is the only upstream dependency. It is a lazy import to avoid circular imports.

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions/cli/` | `ProjectNotFoundError`, `FileLoadError`, `TemplateRenderingError`, `ConfigValidationError`, `ConfigurationError`, `DirectoryError`, `ValidationError` | Medium -- 7 symbols across 7 files |
| `agent_actions/config/` | `ConfigValidationError`, `DependencyError`, `ConfigurationError` | Medium -- 3 symbols across 5 files |
| `agent_actions/input/loaders/` | `DataParseError`, `FileLoadError`, `DependencyError`, `DuplicateFunctionError`, `UDFLoadError`, `AgentActionsException`, `ValidationError` | High -- 7 symbols across 7 files, uses backward-compat aliases |
| `agent_actions/input/preprocessing/` | `AgentActionsException`, `ConfigurationError`, `TransformationError` | Medium -- 3 symbols across 3 files |
| `agent_actions/llm/providers/` | `VendorAPIError`, `RateLimitError`, `NetworkError`, `ConfigurationError`, `DependencyError`, `ValidationError`, `AnthropicError` | High -- 7 symbols across 12+ files |
| `agent_actions/llm/batch/` | `ProcessingError`, `ExternalServiceError`, `ConfigValidationError` | Medium -- 3 symbols across 4 files |
| `agent_actions/llm/realtime/` | `AgentActionsException`, `AgentNotFoundError`, `ConfigurationError`, `TemplateRenderingError` | Medium -- 4 symbols across 4 files |
| `agent_actions/output/` | `AgentActionsException`, `ConfigValidationError`, `SchemaValidationError`, `ConfigurationError`, `ValidationError` | Medium -- 5 symbols across 6 files |
| `agent_actions/processing/` | `ConfigurationError`, `ProcessingError` (as `ProcessorError`), `ValidationError`, `FileLoadError`, `FileWriteError`, `TransformationError`, `SchemaValidationError`, `TemplateVariableError` | High -- 8 symbols across 4 files |
| `agent_actions/prompt/` | `TemplateVariableError`, `TemplateRenderingError`, `ConfigurationError`, `ConfigValidationError`, `AgentActionsException`, `PromptValidationError`, `GenerationError`, `ContextStructureError` (broken), `FileSystemError` | High -- 9 symbols across 7 files |
| `agent_actions/utils/` | `AgentActionsException`, `ConfigurationError`, `DuplicateFunctionError`, `FunctionNotFoundError`, `SchemaValidationError`, `FileSystemError`, `DataValidationError`, `WorkflowError`, `AgentExecutionError` | High -- 9 symbols across 5 files |
| `agent_actions/validation/` | `ConfigurationError`, `SchemaValidationError`, `ConfigValidationError`, `PreFlightValidationError`, `DuplicateFunctionError`, `FunctionNotFoundError`, `UDFLoadError` | Medium -- 7 symbols across 4 files |
| `agent_actions/workflow/` | `AgentActionsException`, `ConfigurationError`, `DependencyError`, `FileSystemError`, `WorkflowError`, `ProcessingError`, `DataValidationError`, `ConfigValidationError` | High -- 8 symbols across 6 files |
| `tests/` (various) | `AgentActionsException`, `ConfigurationError`, `SchemaValidationError`, `TemplateVariableError`, `VendorAPIError`, `ExternalServiceError`, `DuplicateFunctionError`, `FunctionNotFoundError`, `UDFLoadError`, `NetworkError`, `RateLimitError`, `ProjectNotFoundError`, `ValidationError`, `WorkflowError`, `ProcessingError`, `DependencyError`, `ConfigValidationError`, `FileSystemError` | N/A -- test code |

### Dependency Risks

- **[P1-1] Deleting `external.py`**: Zero risk. No file imports from `agent_actions.errors.external`. All imports go through `agent_actions.errors.external_services` (via `__init__.py`).
- **[P1-2] Adding `ContextStructureError`**: `agent_actions/prompt/service.py` (line 333) will fail at runtime if the code path is triggered. Must either define the class in `preflight.py` or change the import.
- **[P2-4] Removing `LoaderError` and `UnsupportedFormatError` aliases**: Zero risk -- no consumers outside `__init__.py`.
- **[P2-4] Migrating `AgentActionsException` to `AgentActionsError`**: High blast radius -- 20+ files across `input/`, `output/`, `processing/`, `prompt/`, `workflow/`, `utils/`, `llm/realtime/`, and tests. Should be done in a single coordinated PR.
- **[P2-4] Migrating `DataParseError` to `ValidationError`**: Moderate blast radius -- `input/loaders/json.py` and `input/loaders/xml.py`.
- **[P2-5] Fixing `TemplateVariableError` base class delegation**: Low risk -- callers in `prompt/service.py`, `processing/processor.py`, and tests access instance attributes directly, not through the base class's `context` dict. But the fix improves consistency.
- **[P2-6] Simplifying `VendorAPIError`**: Moderate risk -- all LLM provider clients (`openai/`, `anthropic/`, `gemini/`, `mistral/`, `cohere/`, `groq/`, `ollama/`) raise `VendorAPIError`. Must audit each call site.
- **[P3-9] Removing unused exceptions**: Low risk for `LoaderError`, `UnsupportedFormatError`. For `SerializationError`, `EnvironmentConfigError`, `ResourceMemoryError`, `InvalidParameterError` -- these may be intended for future use. Consider adding deprecation warnings or `# TODO: remove if unused by <date>` comments.

## Recommended Simplification Order

1. ~~**Delete `external.py`** (P1-1)~~ **DONE** (PR #902)

2. ~~**Define `ContextStructureError` in `preflight.py`** (P1-2)~~ **DONE** (PR #902)

3. ~~**Fix manifest: remove phantom `DependencyValidationError`, move `TemplateVariableError` to correct section** (P1-3)~~ **DONE** (PR #902)

4. ~~**Remove unused aliases `LoaderError`, `UnsupportedFormatError`, `DataParseError`; migrate `DataParseError` call sites** (P2-4, partial)~~ **DONE** (PR #902)

5. ~~**Fix `TemplateVariableError` to properly delegate to base class; make args keyword-only** (P2-5)~~ **DONE** (PR #902)

6. **Extract shared `format_user_message` pattern** (P2-8) -- Reduces ~60 lines of duplicated formatting logic between `SchemaValidationError` and `PreFlightValidationError`.

7. **Plan `AgentActionsException` to `AgentActionsError` migration** (P2-4, remaining) -- Large blast radius, do as a dedicated PR with a deprecation period.

8. **Simplify `VendorAPIError` and `ConfigValidationError` constructors** (P2-6, P2-7) -- Audit call sites first, then consolidate to single clean signatures.

9. **Remove unused exception classes or mark them with deprecation TODO** (P3-9) -- Low priority, evaluate during next cleanup cycle.

10. **Remove `pass` statements from classes that already have docstrings** (P3-10) -- Trivial cleanup, can be batched with any other PR.
