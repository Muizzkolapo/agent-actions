# Config Manifest

## Overview

What: Configuration and initialization surfaces for Agent Actions—schema models, environment
settings, DI container wiring, project initialization, and path management.

Why: Provides a single, consistent source of truth for how workflows are defined, validated,
and wired at runtime.

How: Models (schema + env) define inputs, path resolution anchors IO, and DI wiring connects
orchestration, prompts, and processing to concrete implementations.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [di](di/_MANIFEST.md) | Dependency injection container, registry, and application wiring. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Direct import of `WorkflowConfig` from `schema` (backward-compat alias `WorkflowConfigV2`). | `configuration` |
| `schema.py` | Module | Workflow configuration schema (Pydantic models) with `extra="forbid"` on `ActionConfig` and `DefaultsConfig`, cross-validation (tool `impl` required, duplicate/dangling dep checks, circular dependency detection). | `configuration`, `validation` |
| `environment.py` | Module | Environment settings with validation (validators raise `ValueError` for Pydantic compatibility). | `configuration`, `validation` |
| `paths.py` | Module | `PathManager` with project-boundary-guarded `clean_path()`, scoped root cache, and fallback heuristic warning. | `paths`, `configuration` |
| `path_config.py` | Module | Path configuration: `load_project_config`, `resolve_project_root` (cwd fallback), `get_tool_dirs` (tool dir resolution), `get_schema_path`. | `paths`, `configuration` |
| `factory.py` | Module | DI-aware factory helpers for `ActionRunner`. | `di`, `configuration` |
| `init.py` | Module | `ProjectInitializer` for scaffolding new projects (atomic `create_file`, `yaml.safe_dump`). | `configuration`, `filesystem` |
| `interfaces.py` | Module | Loader/processor/generator interfaces and async mixins. | `configuration`, `interfaces` |
| `defaults.py` | Module | Centralized default constants grouped by domain (`StorageDefaults`, `LockDefaults`, `OllamaDefaults`, `ApiDefaults`, `SeedDataDefaults`, `PromptDefaults`, `DocsDefaults`). Zero imports—safe to import anywhere. | `config`, `defaults` |
| `types.py` | Module | Typed dictionaries (`ActionConfigDict`, `ActionEntryDict`, `ActionConfigMap`, `ContextScopeDict`, `GuardConfigDict`, `WhereClauseDict`, `HitlConfigDict`) and enums (`Granularity`, `RunMode`) for config structures. | `config`, `workflow`, `processing` |
| `project_paths.py` | Module | `ProjectPathsFactory` and `ProjectPaths` for project directory resolution. Moved from `cli/`. | `paths`, `validation`, `output` |
| `manager.py` | Module | `ConfigManager` for workflow config assembly: YAML loading, template rendering, schema validation, config merging, dependency inference, and execution order determination. | `configuration`, `workflow` |

## Flows

### Configuration Bootstrap

```mermaid
flowchart TD
    A[EnvironmentConfig] --> B[ApplicationContainer]
    B --> C[DI Registrations]
    C --> D[ActionRunner]
```

Key Functions

| Module | Symbol | Type | Description |
|--------|--------|------|-------------|
| `environment.py` | `EnvironmentConfig` | Class | Environment settings with validation helpers. |
| `factory.py` | `application_container_context` | Function | Context-managed DI lifecycle for container. |
| `factory.py` | `create_action_runner` | Function | Create `ActionRunner` via DI container. |

### Project Path Resolution

```mermaid
flowchart TD
    A[PathManager] --> B[get_standard_path]
    B --> C[ProjectPathsFactory]
    C --> D[ProjectPaths]
```

Key Functions

| Module | Symbol | Type | Description |
|--------|--------|------|-------------|
| `paths.py` | `PathManager.get_standard_path` | Method | Resolve standard project/agent paths. |
| `paths.py` | `PathManager.get_project_root` | Method | Locate the project root (caches only for CWD lookups). |
| `paths.py` | `PathManager.get_agent_paths` | Method | Resolve per-agent config/io/source paths. |
| `paths.py` | `PathManager.clean_path` | Method | Remove files/dirs with project-boundary guard. |
| `path_config.py` | `load_project_config` | Function | Load project-level config from YAML. |
| `path_config.py` | `resolve_project_root` | Function | Resolve project root, defaulting to `Path.cwd()`. |
| `path_config.py` | `get_project_name` | Function | Return `project_name` from project config, or `None` with warning if absent. |
| `path_config.py` | `get_tool_dirs` | Function | Resolve tool directory names from project config, defaulting to `["tools"]`. |

## Cross-Module Touchpoints

| Package | Why it matters |
|---------|----------------|
| `agent_actions/workflow` | Consumes `WorkflowConfig` (schema) and DI-provisioned runners. Uses `WorkflowRuntimeConfig` for execution context. |
| `agent_actions/validation` | Uses config models and environment settings for startup checks. |
| `agent_actions/prompt` | Relies on resolved paths and DI wiring for prompt preparation. |
| `agent_actions/output` | Uses path resolution to locate IO and schema artifacts. |
| `agent_actions/cli` | Reads config and project paths to render/run workflows. |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `WorkflowConfig` | `agent_config/{workflow}.yml` | Reads | `name`, `description`, `version`, `defaults`, `actions` |
| `ActionConfig` | `agent_config/{workflow}.yml` | Validates | `name`, `intent`, `kind`, `impl`, `model_vendor`, `model_name`, `schema`, `guard`, `dependencies` |
| `DefaultsConfig` | `agent_config/{workflow}.yml` | Validates | `model_vendor`, `model_name`, `granularity`, `run_mode`, `data_source` |
| `EnvironmentConfig` | `.env` | Reads | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AGENT_ACTIONS_ENV` |
| `PathManager.get_project_root` | `agent_actions.yml` | Reads | — |
| `PathManager.get_standard_path` | `agent_io/target/{action}/` | Reads | — |
| `PathManager.clean_path` | `agent_io/target/{action}/` | Writes | — |
| `load_project_config` | `agent_actions.yml` | Reads | `project_name`, `schema_path`, `tool_path`, `seed_data_path` |
| `get_tool_dirs` | `agent_actions.yml` | Reads | `tool_path` |
| `get_schema_path` | `agent_actions.yml` | Reads | `schema_path` |
| `get_seed_data_path` | `agent_actions.yml` | Reads | `seed_data_path` |
| `get_project_name` | `agent_actions.yml` | Reads | `project_name` |
| `ProjectInitializer.init_project` | `agent_actions.yml` | Writes | `project_name`, `default_agent_config`, `schema_path`, `tool_path`, `seed_data_path` |
| `ProjectPathsFactory.create_project_paths` | `prompt_store/{workflow}.md` | Reads | — |
| `ConfigManager.load_configs` | `agent_config/{workflow}.yml` | Reads | `tool_path` |
| `ConfigManager._resolve_dotenv` | `.env` | Reads | — |

**Internal only**: `ActionKind`, `VersionMode`, `VersionConfig`, `MergePattern`, `VersionConsumptionConfig`, `RetryConfig`, `RepromptConfig`, `HitlConfig`, `PathType`, `PathConfig`, `PathManagerError`, `ProjectRootNotFoundError`, `PathManagerValidationError`, `ProcessingMode`, `IAsyncCapable`, `ILoader`, `IProcessor`, `IGenerator`, `IDataLoader`, `ISourceDataLoader`, `IDataProcessor`, `Granularity`, `RunMode`, `ContextScopeDict`, `GuardConfigDict`, `WhereClauseDict`, `HitlConfigDict`, `ActionConfigDict`, `ActionEntryDict`, `ActionConfigMap`, `ProjectPaths`, `StorageDefaults`, `LockDefaults`, `OllamaDefaults`, `ApiDefaults`, `SeedDataDefaults`, `PromptDefaults`, `DocsDefaults` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `agent_actions/validation` | inbound | Validators consume config models and environment settings for startup checks. |
| `agent_actions/workflow` | inbound | Consumes `WorkflowConfig`, DI-provisioned runners, and `ConfigManager` output. |
| `agent_actions/prompt` | inbound | Relies on resolved paths and DI wiring for prompt preparation. |
| `agent_actions/output` | inbound | Uses path resolution to locate IO and schema artifacts. |
| `agent_actions/cli` | inbound | Reads config and project paths to render/run workflows. |
| `agent_actions/errors` | outbound | Raises `ConfigurationError`, `ConfigValidationError`, `FileSystemError`, `FileLoadError`, `TemplateRenderingError`. |
| `agent_actions/guards` | outbound | `GuardParser`/`parse_guard_config` used by `ActionConfig.validate_guard`. |
| `agent_actions/logging` | outbound | Fires config load and validation events via `fire_event`. |
| `agent_actions/utils` | outbound | Uses `FileHandler`, `resolve_absolute_path`, constants. |
| `pydantic` | outbound | Schema models and field validation. |
| `pydantic_settings` | outbound | `EnvironmentConfig` settings loader. |
| `yaml` | outbound | YAML parsing for config files. |
