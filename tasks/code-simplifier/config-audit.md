# Code Simplification Audit: config

**Audited path:** `agent_actions/config/`
**Date:** 2026-02-05
**Modules reviewed:** 11 (8 top-level + 3 in `config/di/`)

## Executive Summary

The `config` package is lean and mostly clean in the current tree; several previously noted dead modules (`bootstrap.py`, `base.py`, `async_processor.py`, `initializer.py`, `loader.py`) no longer exist. The remaining simplification opportunities are modest and mostly internal: duplicated dependency-resolution logic in the DI layer, repetitive registry boilerplate, and a few minor configuration-style redundancies. No high-impact dead-code removals remain in this folder.

## Priority Findings

### P2 — Medium Impact (Meaningful improvement, moderate effort)

1. **Duplicated dependency-resolution logic in DI container**
   - **Files:** `agent_actions/config/di/container.py`
   - **Lines:** `_create_instance` (around lines 83-131) vs `_create_with_dependencies` (around lines 245-286)
   - **What:** Both methods perform nearly identical parameter inspection, type-hint resolution, default handling, and `DependencyError` construction. The only difference is `_create_with_dependencies` accepts `override_kwargs`.
   - **Why:** Any change to dependency resolution rules must be applied twice. A shared helper (e.g., `_build_init_kwargs(cls, overrides=None)`) would reduce duplication and risk of drift.
   - **Risk:** Low. Internal refactor, no API change.

### P3 — Low Impact (Nice-to-have, minor cleanups)

2. **ProcessorRegistry has 4 parallel dicts with identical boilerplate**
   - **File:** `agent_actions/config/di/container.py`
   - **Lines:** `ProcessorRegistry` methods `register_*`, `get_*`, `list_*`
   - **What:** `_processors`, `_loaders`, `_generators`, `_services` repeat the same patterns for registration and lookup.
   - **Why:** A single registry map keyed by category would reduce ~40 lines and keep behavior consistent.
   - **Risk:** Low, but would change internal API. Optional.

3. **`PathConfig.for_environment()` has redundant defaults**
   - **File:** `agent_actions/config/paths.py`
   - **Lines:** ~47-56
   - **What:** The `"dev"` config `cls(create_if_missing=True)` is identical to the default `cls()` since `create_if_missing` already defaults to `True`. The `"prod"` config only changes `create_if_missing=False`.
   - **Why:** The `"dev"` entry adds no value and makes the defaults look more complex than they are.
   - **Risk:** None. Pure simplification.

4. **`ApplicationContainer.create_for_environment()` uses if/elif chain**
   - **File:** `agent_actions/config/di/application.py`
   - **Lines:** ~116-142
   - **What:** The method uses an if/elif chain to select a configuration profile.
   - **Why:** A dict lookup would be shorter and easier to extend.
   - **Risk:** None.

5. **Testing-only wiring lives in production module**
   - **File:** `agent_actions/config/di/configurator.py`
   - **Lines:** `configure_for_testing()` (~66-112)
   - **What:** Inline `Mock()` setup for processors/loaders is embedded in production code.
   - **Why:** This is acceptable but adds test-only concerns to a production module. If testing config grows, it may be cleaner to move test wiring into test utilities.
   - **Risk:** Low. Style concern only.

## Module-by-Module Breakdown

### `__init__.py`
- **Lines:** 3
- **Complexity:** Trivial
- **Findings:** None.

### `schema.py`
- **Lines:** ~222
- **Complexity:** Low. Clean Pydantic models.
- **Findings:** None specific to simplification.

### `environment.py`
- **Lines:** ~157
- **Complexity:** Low.
- **Findings:** None.

### `paths.py`
- **Lines:** ~442
- **Complexity:** Medium.
- **Findings:** P3-3 (redundant `dev` entry in `PathConfig.for_environment`).

### `path_config.py`
- **Lines:** ~58
- **Complexity:** Low.
- **Findings:** None.

### `factory.py`
- **Lines:** ~70
- **Complexity:** Low.
- **Findings:** None.

### `init.py`
- **Lines:** ~99
- **Complexity:** Low.
- **Findings:** None.

### `interfaces.py`
- **Lines:** ~216
- **Complexity:** Medium.
- **Findings:** None.

### `di/container.py`
- **Lines:** ~299
- **Complexity:** Medium.
- **Findings:** P2-1 (duplicated dependency-resolution logic), P3-2 (registry boilerplate).

### `di/configurator.py`
- **Lines:** ~146
- **Complexity:** Low.
- **Findings:** P3-5 (testing-only wiring in production module).

### `di/application.py`
- **Lines:** ~227
- **Complexity:** Medium.
- **Findings:** P3-4 (if/elif environment selection).

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions/errors` | `ConfigValidationError`, `DependencyError`, `ConfigurationError` | `environment.py`, `schema.py`, `di/container.py`, `di/application.py` |
| `agent_actions/logging` | `LoggerFactory` | `di/configurator.py` |
| `agent_actions/workflow` | `AgentRunner` | `factory.py`, `di/application.py` |
| `agent_actions/input` | `DataProcessor`, `SourceDataLoader` | `di/application.py`, `di/configurator.py` |
| `agent_actions/prompt` | `DataGenerator`, `PromptLoader` | `di/application.py`, `di/configurator.py` |
| `agent_actions/llm` | `BatchService` | `di/configurator.py`, `di/application.py` |
| `agent_actions/utils` | `API_KEY_KEY`, `MODEL_NAME_KEY`, `CHUNK_CONFIG_KEY` | `init.py` |
| `agent_actions/storage` | `StorageBackend` (TYPE_CHECKING) | `factory.py`, `di/application.py` |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions/workflow` | `ProcessorFactory`, `create_agent_runner` | High |
| `agent_actions/input` | `IDataLoader`, `ISourceDataLoader`, `ProcessingMode`, `registry` | High |
| `agent_actions/prompt` | `IGenerator`, `ProcessingMode`, `registry` | High |
| `agent_actions/llm` | `EnvironmentConfig`, `load_project_config`, `PathManager`, `registry` | High |
| `agent_actions/cli` | `ProjectInitializer`, `PathManager`, `PathType` | Medium |
| `agent_actions/validation` | `EnvironmentConfig` | Medium |
| `tests/` | `ProcessorFactory`, `Granularity`, `ActionConfig` | Low |

## Dependency Risks

- **P2-1 (DI resolution helper):** Internal refactor only; no external callers affected as long as the resolution behavior is preserved.
- **P3-2 (registry consolidation):** Would change internal API; keep this as an optional cleanup rather than a must-do.
- **P3-5 (testing wiring location):** Purely organizational.

## Recommended Simplification Order

1. **P2-1 — Deduplicate DI resolution logic** in `container.py`.
2. **P3-3 — Remove redundant `dev` entry** in `PathConfig.for_environment`.
3. **P3-4 — Replace if/elif with dict lookup** in `ApplicationContainer.create_for_environment`.
4. **P3-2 — Consider registry consolidation** only if you want to reduce boilerplate further.
5. **P3-5 — Optionally move test wiring** if the test container grows.
