# Code Simplification Audit: logging

**Audited path:** `agent_actions/logging/`
**Date:** 2026-02-05
**Modules reviewed:** 37 Python files (5,787 total lines)
**Status:** ✅ COMPLETED (Phase 1)

---

## Completed Items (PR #905)

| Finding | Description | Resolution |
|---------|-------------|------------|
| P1-3 | Duplicate event codes B004-B007 | Renumbered to B009-B012 |
| P1-1 | Duplicated `level_order` in 4 files | Extracted `EventLevel.ordered()` classmethod |
| P1-2 | Triplicated Rich availability check | Created `core/_compat.py` |
| P2-9 | Unused level mixin classes | Removed `DebugLevel`, `InfoLevel`, `WarnLevel`, `ErrorLevel` |
| P2-10 | Unused handler classes | Removed `QuietConsoleHandler`, `VerboseConsoleHandler` |
| P2-14 | Dead `redact_patterns` config | Removed field from `LoggingConfig` |

**Lines removed:** ~150
**PR:** https://github.com/Muizzkolapo/agent-actions/pull/905

---

## Deferred Items (Not Blocking)

| Finding | Reason |
|---------|--------|
| P2-11 | `StructuredLogHandler` exported in public API; deprecate first |
| P2-12 | `JSONFormatter` exported in public API; tests exist |
| P1-4 | `RedactingFilter` inverted dependency requires moving util to `agent_actions/utils`; separate PR |
| P2-6/P2-7 | `events/types.py` boilerplate reduction (2,657 lines); high effort, defer to follow-up |
| P2-8 | `events/__init__.py` maintenance burden; lower priority after types.py split |

---

## Executive Summary

The logging subsystem is architecturally sound -- it implements a well-structured event-based system inspired by dbt. However, it contains significant boilerplate duplication (the 2,657-line `events/types.py` file accounts for 46% of the entire folder), four copies of the same level-comparison logic, three independent Rich-availability-check blocks, duplicate event codes, unused exports, and an inverted dependency from the logging layer into the LLM layer. The highest-impact simplification opportunities center on extracting repeated patterns into shared utilities and removing dead code, which would eliminate roughly 100+ lines without changing any public API.

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

1. **Duplicated `level_order` comparison across 4 files.** The exact same `level_order = [EventLevel.DEBUG, EventLevel.INFO, EventLevel.WARN, EventLevel.ERROR]` list and index-comparison pattern is repeated in `core/protocols.py:109`, `core/handlers/console.py:95`, `core/handlers/json_file.py:84`, and `core/handlers/structured.py:75`. Each also re-imports `EventLevel` locally. This should be a single method on `EventLevel` (e.g., `EventLevel.__ge__` or a `level_at_least(event_level, min_level)` utility).
   - **Files:** `core/protocols.py`, `core/handlers/console.py`, `core/handlers/json_file.py`, `core/handlers/structured.py`
   - **Risk:** Low. Internal implementation detail; no public API change.

2. **Triplicated Rich availability check.** The `try: from rich.console import Console; RICH_AVAILABLE = True except ImportError: RICH_AVAILABLE = False` block is copied verbatim in three files: `core/handlers/console.py:19-25`, `core/handlers/context_debug.py:18-25`, and `events/formatters.py:17-23`. Extract to a shared `_compat.py` or similar.
   - **Files:** `core/handlers/console.py`, `core/handlers/context_debug.py`, `events/formatters.py`
   - **Risk:** Low. No behavioral change.

3. **Duplicate event codes in `events/types.py`.** The batch event codes B004, B005, B006, and B007 are each used by two different event classes:
   - `B004`: `BatchProcessingCompleteEvent` (line 442) AND `BatchSubmissionFailedEvent` (line 1083)
   - `B005`: `BatchResultsProcessedEvent` (line 463) AND `BatchStatusCheckFailedEvent` (line 1106)
   - `B006`: `BatchErrorEvent` (line 486) AND `BatchResultProcessingFailedEvent` (line 1127)
   - `B007`: `BatchPassthroughEvent` (line 505) AND `BatchPartialFailureEvent` (line 1150)
   - **Risk:** Medium. These collisions mean the `code` property does not uniquely identify event types, which undermines the event code system's purpose. Fix requires assigning new codes to the later batch error events (e.g., B009-B012).

4. **Inverted dependency: `filters.py` imports from `agent_actions.llm`.** Line 9 of `filters.py` imports `BaseClient.redact_sensitive_data` from the LLM providers layer. A logging utility should not depend on an LLM client class. The `redact_sensitive_data` method should be extracted to `agent_actions.utils` or the redaction logic should be inlined in the filter.
   - **File:** `filters.py:9, 175`
   - **Risk:** Medium. Requires moving a utility method; downstream consumers of `BaseClient.redact_sensitive_data` would need updating.

5. **Duplicate redact pattern lists in `config.py` and `filters.py`.** The default redaction patterns are defined in two places: `LoggingConfig.redact_patterns` default (lines 34-40 and the identical fallback at lines 73-80) and `RedactingFilter.DEFAULT_PATTERNS` (lines 23-31). These lists are not even consistent with each other -- one uses simple keyword patterns while the other uses value-matching regexes.
   - **Files:** `config.py:34-40`, `config.py:73-80`, `filters.py:23-31`
   - **Risk:** Low. Consolidate to a single source of truth.

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

6. **`events/types.py` is a 2,657-line God file.** This single file defines 80+ event dataclasses. Each event follows an identical boilerplate pattern: fields, `__post_init__` that sets level/category/message/data, and a `code` property. The file could be split into domain-aligned submodules (workflow_events.py, agent_events.py, batch_events.py, llm_events.py, etc.) or the boilerplate could be reduced via a base class helper or decorator.
   - **File:** `events/types.py` (2,657 lines)
   - **Risk:** Medium. The `events/__init__.py` re-exports everything, so splitting is non-breaking if the `__init__.py` is maintained.

7. **Repetitive `__post_init__` boilerplate in event types.** Every event class in `events/types.py` follows the same pattern: set `self.level`, set `self.category`, build `self.message` from fields, manually copy all fields into `self.data = {...}`. The `self.data` dict duplicates every field already on the dataclass. A base class method or metaclass could auto-populate `self.data` from dataclass fields, eliminating thousands of lines.
   - **File:** `events/types.py` (every event class)
   - **Risk:** Medium. Behavioral change if any consumer relies on `data` containing exactly the current keys. Requires careful testing.

8. **`events/__init__.py` is a 270-line pass-through.** It re-imports and re-exports all 80+ event types from `events/types.py` with a verbatim copy of every name in both the import block and the `__all__` list. Any new event requires updating three places (types.py, __init__.py imports, __init__.py __all__). Consider using wildcard imports or generating `__all__` programmatically.
   - **File:** `events/__init__.py` (270 lines)
   - **Risk:** Low-Medium. Wildcard imports reduce maintainability hints but reduce triple-maintenance burden.

9. **Unused level mixin classes.** `DebugLevel`, `InfoLevel`, `WarnLevel`, and `ErrorLevel` mixins in `core/events.py:150-171` are defined but never used anywhere in the codebase. All event types set their level in `__post_init__` instead.
   - **File:** `core/events.py:150-171`
   - **Risk:** Low. Dead code removal.

10. **Unused handler classes.** `QuietConsoleHandler` and `VerboseConsoleHandler` (console.py:169-193) are defined but never instantiated or referenced outside their own file. The factory achieves the same effect by passing `min_level` to `ConsoleEventHandler`.
    - **File:** `core/handlers/console.py:169-193`
    - **Risk:** Low. Dead code removal.

11. **`StructuredLogHandler` and `StructuredFormatter` appear unused.** These classes in `core/handlers/structured.py` (225 lines) are exported via `__init__.py` but never imported or used outside the logging folder itself. If they exist purely as infrastructure for future use, they are dead code today.
    - **File:** `core/handlers/structured.py` (225 lines)
    - **Risk:** Low-Medium. Confirm no external usage before removing.

12. **`JSONFormatter` (formatters.py) appears unused.** The `JSONFormatter` class (137 lines) is exported in `__init__.py` but never imported outside the logging folder. It is a `logging.Formatter` subclass for the old Python logging system. With the event system in place, this may be obsolete.
    - **File:** `formatters.py` (137 lines)
    - **Risk:** Low-Medium. Confirm no external usage before removing.

13. **`RedactingFilter` appears unused.** `RedactingFilter` is exported in `__init__.py` but never imported or used outside the logging folder. The old Python logging filter system has been replaced by the event system.
    - **File:** `filters.py` (175 lines)
    - **Risk:** Low-Medium. Confirm no external usage before removing. Note: the inverted LLM dependency (P1-4) also lives here.

14. **`LoggingConfig.redact_patterns` is configured but never consumed.** The `redact_patterns` field on `LoggingConfig` is set from config/environment but is never passed to `RedactingFilter` during initialization. The factory does not create or attach any `RedactingFilter`.
    - **File:** `config.py:33-40`, `factory.py` (no usage of `redact_patterns`)
    - **Risk:** Low. Either wire it up or remove the field.

### P3 -- Low Impact (Nice-to-have, minor cleanups)

15. **`context.py` is a deprecated shim.** The 25-line file exists solely for backwards compatibility, re-exporting `EventManager` and `get_manager`. The deprecation notice is thorough. Consider setting a timeline for removal or adding a deprecation warning at import time.
    - **File:** `context.py` (25 lines)
    - **Risk:** Low. Backwards-compat shim; removal requires checking for imports.

16. **Backwards compatibility aliases in `factory.py`.** Lines 377-379 define `initialize_events`, `set_event_context`, and `flush_events` as aliases. Like `context.py`, these exist for migration. Consider runtime deprecation warnings.
    - **File:** `factory.py:377-379`
    - **Risk:** Low.

17. **`datetime.utcnow()` usage (deprecated in Python 3.12+).** `core/handlers/structured.py:209` uses `datetime.utcnow()` which is deprecated. The rest of the codebase correctly uses `datetime.now(timezone.utc)`.
    - **File:** `core/handlers/structured.py:209`
    - **Risk:** Low. Single-line fix for consistency.

18. **Redundant `from_project_config` default duplication in `config.py`.** The `from_project_config` classmethod (lines 54-83) manually specifies defaults for every field that already have defaults in the dataclass definition. The `redact_patterns` fallback (lines 73-80) is an exact copy of the class-level default (lines 34-40). Use `cls()` defaults or a shared constant.
    - **File:** `config.py:54-83`
    - **Risk:** Low.

19. **Long if-elif chain in `events/formatters.py:72-99`.** The `format()` method dispatches on `event_type` string with 10 elif branches. A dictionary dispatch (mapping event_type string to formatter method) would be cleaner.
    - **File:** `events/formatters.py:72-99`
    - **Risk:** Low. Purely stylistic.

20. **Long if-elif chain in `events/handlers/run_results.py:153-168`.** Same pattern -- `handle()` dispatches on `event_type` with 8 elif branches. Dictionary dispatch would be cleaner.
    - **File:** `events/handlers/run_results.py:153-168`
    - **Risk:** Low. Purely stylistic.

21. **`_extract_provider_name` in error formatter base.** The method (`base.py:47-72`) uses a hardcoded list of provider names. This could reference a central provider registry or constants instead of scattering provider knowledge into the error formatter.
    - **File:** `errors/formatters/base.py:47-72`
    - **Risk:** Low.

22. **Unreachable code in `filters.py` replacement logic.** In `RedactingFilter.__init__` (lines 60-65), the `sk-ant` check comes after the `sk-` check but `sk-ant-...` would already match `sk-`. The `sk-ant` branch is unreachable.
    - **File:** `filters.py:60-65`
    - **Risk:** Low. Bug in dead code (RedactingFilter itself appears unused).

## Module-by-Module Breakdown

### `__init__.py`
- **Lines:** 57
- **Complexity:** Low
- **Findings:** Clean re-export module. No issues.

### `config.py`
- **Lines:** 136
- **Complexity:** Low-Medium
- **Findings:** P1-5 (duplicate redact_patterns defaults), P3-18 (redundant defaults in `from_project_config`), P2-14 (`redact_patterns` configured but never consumed).

### `context.py`
- **Lines:** 25
- **Complexity:** Low
- **Findings:** P3-15 (deprecated shim, consider removal timeline).

### `factory.py`
- **Lines:** 379
- **Complexity:** Medium. The `initialize()` method (lines 63-199) is 137 lines with moderate nesting.
- **Findings:** P3-16 (backwards compat aliases), P2-14 (`redact_patterns` never wired to filter).

### `filters.py`
- **Lines:** 175
- **Complexity:** Medium
- **Findings:** P1-4 (inverted dependency on `agent_actions.llm`), P1-5 (duplicate redact patterns), P2-13 (appears unused), P3-22 (unreachable `sk-ant` branch).

### `formatters.py`
- **Lines:** 137
- **Complexity:** Low-Medium
- **Findings:** P2-12 (appears unused outside logging folder).

### `core/__init__.py`
- **Lines:** 59
- **Complexity:** Low
- **Findings:** Re-export module. Exports `StructuredLogHandler` (P2-11, potentially unused).

### `core/events.py`
- **Lines:** 171
- **Complexity:** Low
- **Findings:** P2-9 (unused level mixin classes at lines 150-171).

### `core/manager.py`
- **Lines:** 266
- **Complexity:** Low-Medium
- **Findings:** Clean implementation. Singleton pattern is well-implemented. No significant issues.

### `core/protocols.py`
- **Lines:** 128
- **Complexity:** Low
- **Findings:** P1-1 (duplicated `level_order` comparison logic at line 109).

### `core/handlers/bridge.py`
- **Lines:** 196
- **Complexity:** Medium. Mixes handler class with event dataclass definitions in the same file (imports at line 130 break module structure conventions).
- **Findings:** The file defines both `LoggingBridgeHandler` (a `logging.Handler` subclass) and three event dataclasses (`LogEvent`, `DebugEvent`, `SystemEvent`). The event classes should arguably live in `core/events.py` alongside `BaseEvent`.

### `core/handlers/console.py`
- **Lines:** 192
- **Complexity:** Low-Medium
- **Findings:** P1-1 (duplicated level_order), P1-2 (duplicated Rich check), P2-10 (unused `QuietConsoleHandler`, `VerboseConsoleHandler`).

### `core/handlers/context_debug.py`
- **Lines:** 367
- **Complexity:** Medium. Two near-identical display methods (`_display_rich_summary` and `_display_plain_summary`) with ~60 lines each duplicating the same structure.
- **Findings:** P1-2 (duplicated Rich check). The `_display_rich_summary` / `_display_plain_summary` duplication could be reduced with a template/strategy for output, but this is a lower priority.

### `core/handlers/json_file.py`
- **Lines:** 173
- **Complexity:** Low-Medium
- **Findings:** P1-1 (duplicated level_order).

### `core/handlers/structured.py`
- **Lines:** 225
- **Complexity:** Low-Medium
- **Findings:** P1-1 (duplicated level_order), P2-11 (appears unused), P3-17 (deprecated `datetime.utcnow()`).

### `errors/__init__.py`
- **Lines:** 53
- **Complexity:** Low
- **Findings:** Clean facade. Upstream dependency on `agent_actions.utils.safe_format`.

### `errors/translator.py`
- **Lines:** 82
- **Complexity:** Low
- **Findings:** Clean strategy-pattern implementation. Upstream dependency on `agent_actions.utils.safe_format`.

### `errors/user_error.py`
- **Lines:** 117
- **Complexity:** Low
- **Findings:** Clean data structure. No issues.

### `errors/formatters/base.py`
- **Lines:** 72
- **Complexity:** Low
- **Findings:** P3-21 (hardcoded provider names).

### `errors/formatters/api.py`
- **Lines:** 64
- **Complexity:** Low
- **Findings:** Clean. No significant issues.

### `errors/formatters/authentication.py`
- **Lines:** 59
- **Complexity:** Low
- **Findings:** Clean. No significant issues.

### `errors/formatters/configuration.py`
- **Lines:** 167
- **Complexity:** Medium. `_format_missing_required_fields_error` (lines 74-141) is 68 lines with significant string building. Three loops over `missing_fields` with near-identical body (lines 93-99, 109-115, 126-132).
- **Findings:** The three loops building fix examples for different config levels (`project`, `workflow`, `action`) repeat the same field-to-example mapping. Could be extracted to a helper.

### `errors/formatters/file.py`
- **Lines:** 68
- **Complexity:** Low
- **Findings:** Clean.

### `errors/formatters/function.py`
- **Lines:** 97
- **Complexity:** Low
- **Findings:** Clean. Good use of `SequenceMatcher`.

### `errors/formatters/generic.py`
- **Lines:** 33
- **Complexity:** Low
- **Findings:** Clean fallback formatter.

### `errors/formatters/model.py`
- **Lines:** 78
- **Complexity:** Low
- **Findings:** Hardcoded model suggestions (lines 69-78) will go stale as models are deprecated/released. Consider pulling from a central model registry if one exists.

### `errors/formatters/template.py`
- **Lines:** 131
- **Complexity:** Low-Medium
- **Findings:** Good use of `SequenceMatcher` for "did you mean" suggestions. Clean implementation.

### `errors/formatters/yaml.py`
- **Lines:** 158
- **Complexity:** Low-Medium
- **Findings:** Clean. Good code snippet display logic.

### `errors/services/context.py`
- **Lines:** 72
- **Complexity:** Low-Medium
- **Findings:** Clean. The `dir()` iteration over exception attributes (lines 55-66) is broad but appropriately guarded.

### `events/__init__.py`
- **Lines:** 270
- **Complexity:** Low (but high maintenance burden)
- **Findings:** P2-8 (triple-maintenance re-export problem).

### `events/formatters.py`
- **Lines:** 252
- **Complexity:** Medium
- **Findings:** P1-2 (duplicated Rich check), P3-19 (long if-elif dispatch chain).

### `events/types.py`
- **Lines:** 2,657
- **Complexity:** Low per-class, but High in aggregate (80+ classes)
- **Findings:** P1-3 (duplicate event codes), P2-6 (God file), P2-7 (repetitive boilerplate).

### `events/handlers/run_results.py`
- **Lines:** 326
- **Complexity:** Medium
- **Findings:** P3-20 (long if-elif dispatch chain).

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions.llm.providers.client_base` | `BaseClient.redact_sensitive_data` | `filters.py:9,175` |
| `agent_actions.utils.safe_format` | `safe_format_error`, `safe_get_exception_message`, `format_exception_chain_for_debug`, `extract_root_cause` | `errors/__init__.py:8-11`, `errors/translator.py:6` |
| `yaml` (PyYAML, stdlib-external) | `yaml.YAMLError` | `errors/formatters/yaml.py:5,17` |
| `rich.console`, `rich.tree` | `Console`, `Tree` | `core/handlers/console.py`, `core/handlers/context_debug.py`, `events/formatters.py` |
| `difflib` | `SequenceMatcher` | `errors/formatters/function.py:3`, `errors/formatters/template.py:3` |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions.cli` | `LoggerFactory`, `LoggingConfig`, `fire_event`, `format_user_error`, event types | High -- CLI is the primary consumer of the full logging API |
| `agent_actions.workflow` | `fire_event`, `get_manager`, event types (Workflow*, Agent*, Batch*) | High -- workflow orchestration is deeply integrated |
| `agent_actions.llm.providers.*` | `fire_event`, `LLMRequestEvent`, `LLMResponseEvent`, `LLMErrorEvent`, `RateLimitEvent`, `LLMJSONParseErrorEvent` | Medium -- all 7 LLM providers import event types |
| `agent_actions.llm.batch.*` | `fire_event`, `get_manager`, batch event types | Medium |
| `agent_actions.processing` | `fire_event`, data processing event types, `format_user_error` | Medium |
| `agent_actions.prompt` | `fire_event`, `ContextFieldNotFoundEvent`, context event types | Medium |
| `agent_actions.validation` | `fire_event`, `format_user_error`, `ValidationStartEvent`, `ValidationCompleteEvent` | Medium |
| `agent_actions.output` | `fire_event`, `LoggerFactory`, file I/O event types | Medium |
| `agent_actions.config` | `fire_event`, `LoggerFactory`, config event types | Low-Medium |
| `agent_actions.input` | `fire_event`, data event types | Low |
| `agent_actions.utils` | `fire_event`, `format_user_error`, cache event types | Low |

### Dependency Risks

- **P1-4 (inverted LLM dependency):** Removing the `BaseClient` import from `filters.py` would break the coupling between logging and LLM layers. If `filters.py` is dead code (P2-13), the cleanest fix is removal. If it needs to stay, the `redact_sensitive_data` utility should move to `agent_actions.utils`.
- **P1-3 (duplicate event codes):** If any downstream consumer uses event codes (e.g., `ContextDebugHandler` matches on codes like "CX001"), duplicate B-codes could cause incorrect event routing or confusing logs. The fix (renumbering) would not affect external API but could change log output.
- **P2-6 (splitting types.py):** The `events/__init__.py` already re-exports everything, so downstream consumers importing from `agent_actions.logging.events` would not break. However, any consumer importing directly from `agent_actions.logging.events.types` would need updating. A grep shows several files do import directly from `events.types` (e.g., `processing/error_handling.py`, `prompt/context/scope.py`, `llm/providers/mixins.py`).
- **P2-11 (removing StructuredLogHandler):** Only exported from `core/__init__.py`. No external consumers found. Safe to remove or mark as experimental.
- **P2-12, P2-13 (removing JSONFormatter, RedactingFilter):** Both are exported in the top-level `__init__.py.__all__`. Removing them is an API-breaking change, though no in-tree consumers exist.

## Recommended Simplification Order

1. **Fix duplicate event codes (P1-3).** Quick fix, prevents data integrity issues in logging. Renumber `BatchSubmissionFailedEvent` through `BatchPartialFailureEvent` to B009-B012.

2. **Extract `level_order` comparison into `EventLevel` (P1-1).** Add a comparison method to `EventLevel` (or make it an `IntEnum`) and remove the four duplicated lists. Estimated ~20 lines removed.

3. **Extract Rich availability check (P1-2).** Create a shared `_compat.py` with `RICH_AVAILABLE` and optional `Console`/`Tree` imports. Removes three duplicated try/except blocks.

4. **Remove unused code (P2-9, P2-10, P2-11, P2-12, P2-13, P2-14).** Audit and remove: level mixins (22 lines), `QuietConsoleHandler`/`VerboseConsoleHandler` (24 lines), potentially `StructuredLogHandler`/`StructuredFormatter` (225 lines), potentially `JSONFormatter` (137 lines), potentially `RedactingFilter` (175 lines), and the dead `redact_patterns` config field. This is the highest line-count reduction (~580+ lines) but requires confirming no external usage (e.g., user-facing plugins).

5. **Fix inverted dependency (P1-4).** Move `redact_sensitive_data` to `agent_actions.utils` or inline the logic. If RedactingFilter is removed (step 4), this is resolved automatically.

6. **Consolidate redact patterns (P1-5).** Define a single `DEFAULT_REDACT_PATTERNS` constant and reference it from both `config.py` and `filters.py`. If RedactingFilter is removed, this simplifies to just removing the duplicated fallback in `config.py`.

7. **Reduce `events/types.py` boilerplate (P2-7).** Implement auto-population of `self.data` from dataclass fields in `BaseEvent.__post_init__`. This is the highest-effort change but could eliminate ~1,500 lines of manual `self.data = {...}` code.

8. **Split `events/types.py` into domain modules (P2-6).** After reducing boilerplate, split into ~8 domain-specific files. Update `events/__init__.py` accordingly.

9. **Simplify `events/__init__.py` maintenance (P2-8).** After splitting types.py, consider generating `__all__` programmatically or using a wildcard re-export pattern.

10. **Address remaining P3 items.** Fix `datetime.utcnow()`, add deprecation warnings to compat shims, refactor if-elif chains to dict dispatch, etc.
