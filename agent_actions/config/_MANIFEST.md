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
| `__init__.py` | Module | Package exports for configuration models. | `configuration` |
| `schema.py` | Module | Workflow configuration schema (Pydantic models). | `configuration`, `validation` |
| `environment.py` | Module | Environment settings with validation and API/perf adapters. | `configuration`, `validation` |
| `paths.py` | Module | PathManager and standard path resolution. | `paths`, `configuration` |
| `path_config.py` | Module | Path configuration models and defaults. | `paths`, `configuration` |
| `factory.py` | Module | DI-aware factory helpers for `AgentRunner`. | `di`, `configuration` |
| `initializer.py` | Module | Startup validation and container lifecycle helpers. | `configuration`, `validation` |
| `init.py` | Module | ProjectInitializer for scaffolding new projects. | `configuration`, `filesystem` |
| `async_processor.py` | Module | Async processing base classes and helpers. | `async`, `configuration` |
| `base.py` | Module | Artifact base classes with secure read/write helpers. | `artifacts`, `filesystem` |
| `interfaces.py` | Module | Loader/processor/generator interfaces and async mixins. | `configuration`, `interfaces` |
| `bootstrap.py` | Module | Legacy DI bootstrap configuration. | `di`, `configuration` |
| `loader.py` | Module | Reserved for config loading utilities (empty). | `configuration` |

## Flows

### Configuration Bootstrap

```mermaid
flowchart TD
    A[EnvironmentConfig] -->|validate_startup| B[Startup Validation]
    B --> C[ApplicationContainer]
    C --> D[DI Registrations]
    D --> E[AgentRunner]
```

Key Functions

| Module | Symbol | Type | Description |
|--------|--------|------|-------------|
| `environment.py` | `EnvironmentConfig` | Class | Environment settings with validation helpers. |
| `initializer.py` | `initialize_application` | Function | Run startup validation and build env config. |
| `initializer.py` | `application_container_context` | Function | Context-managed DI lifecycle with validation. |
| `factory.py` | `create_agent_runner` | Function | Create `AgentRunner` via DI container. |

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
| `paths.py` | `PathManager.get_project_root` | Method | Locate the project root for path resolution. |
| `paths.py` | `PathManager.get_agent_paths` | Method | Resolve per-agent config/io/source paths. |
| `path_config.py` | `load_project_config` | Function | Load project-level config from YAML. |

### Async Processing Mode

```mermaid
flowchart TD
    A[ProcessingContext] -->|mode decision| B{SYNC/ASYNC/AUTO}
    B -->|ASYNC| C[BaseAsyncProcessor]
    B -->|SYNC| D[Sync Processor]
```

Key Functions

## Cross-Module Touchpoints

| Package | Why it matters |
|---------|----------------|
| `agent_actions/workflow` | Consumes `WorkflowConfigV2` and DI-provisioned runners. |
| `agent_actions/validation` | Uses config models and environment settings for startup checks. |
| `agent_actions/prompt` | Relies on resolved paths and DI wiring for prompt preparation. |
| `agent_actions/output` | Uses path resolution to locate IO and schema artifacts. |
| `agent_actions/cli` | Reads config and project paths to render/run workflows. |

| Module | Symbol | Type | Description |
|--------|--------|------|-------------|
| `interfaces.py` | `ProcessingMode` | Enum | Processing mode selection (sync/async/auto). |
| `async_processor.py` | `BaseAsyncProcessor.process_items_parallel` | Method | Async parallel processing with concurrency control. |
| `async_processor.py` | `ProcessingContext.should_use_async` | Method | Decide async execution for AUTO mode. |
