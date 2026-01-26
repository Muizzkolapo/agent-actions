# DI Manifest

## Overview

Dependency injection helpers for Agent Actions. The package wires up logging, path
resolution, processors, loaders, and generator implementations so that both CLI
commands and runtime workflows can request concrete implementations without
manually instantiating dependencies.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `application.py` | Module | Application container that bootstraps the DI stack and exposes factories. | `agent_actions.workflow.runner`, `config.paths`, `config.di.container` |
| `ApplicationContainer` | Class | Central entry point for DI-bound factories, runners, and processors. | `agent_actions.workflow.runner`, `agent_actions.llm.batch` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `__init__` | Method | Build the container either with provided config or a default profile. | `config.di.configurator` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_runner` | Method | Instantiate `AgentRunner` injected with shared processor factory and tool flag. | `agent_actions.workflow.runner` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processor_factory` | Method | Return the DI-aware `ProcessorFactory`. | `config.di.container` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_dependency_container` | Method | Expose the underlying container for ad-hoc lookups (testing, helpers). | `config.di.container` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_get_dependency_configs_for_agent` | Method | Helper that extracts config maps for dependencies referenced by an agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_get_source_loader` | Method | Resolve `ISourceDataLoader` with fallback strategies when the container lacks a registration. | `agent_actions.errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_get_data_generator` | Method | Resolve generator from the container or build a fallback `DataGenerator`. | `agent_actions.prompt.data_generator` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_get_data_processor` | Method | Resolve processor or instantiate `DataProcessor`. | `agent_actions.input.preprocessing.processing` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_for_environment` | Class Method | Build an `ApplicationContainer` configured for `development`, `production`, or `testing`. | `config.di.configurator` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_for_testing` | Class Method | Create test-ready container with mocked dependencies. | `config.di.configurator` |
| `configurator.py` | Module | Static helper that registers core services, processors, and utilities in the DI container. | `config.di.container`, `agent_actions.logging.factory` |
| `DIConfigurator` | Class | Encapsulates container registration logic and test scaffolding. | `agent_actions.logging.factory` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `configure_container` | Method | Register singletons/transients for path management, batch service, processors, and loaders. | `config.di.container` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_processor_factory` | Method | Build a `ProcessorFactory` wired with the shared registry. | `config.di.container` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `configure_for_testing` | Method | Assemble a container with mocked services for unit tests. | `unittest.mock` |
| `ConfigurationProfile` | Class | Preset configuration dictionaries for `development`, `production`, and `testing`. | - |
| `container.py` | Module | Lightweight dependency injection container, registry, and factory helpers. | `errors`, `threading`, `inspect`
| `ServiceLifetime` | Class | Enum-like constants for singleton, transient, and scoped lifetimes. | - |
| `ServiceDescriptor` | Dataclass | Metadata holder describing how to instantiate registered services. | - |
| `DependencyContainer` | Class | Register/resolver that creates instances with automatic dependency wiring. | `agent_actions.errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_singleton/transient/factory/instance` | Methods | Register services via different lifetimes or direct instances. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get` | Method | Resolve a dependency, instantiate if needed, or raise `DependencyError`. | `agent_actions.errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_create_instance` | Method | Inspect constructor parameters, resolve dependencies, and instantiate safely. | `inspect`, `typing`
| `ProcessorRegistry` | Class | Decorator-driven registry for processors, loaders, generators, and services. | `agent_actions.errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_*` | Methods | Decorators used by runtime components to self-register. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_*` | Methods | Retrieve registered implementation classes, raising `ConfigurationError` if missing. | `agent_actions.errors` |
| `ProcessorFactory` | Class | Factory that constructs processors/loaders/generators/services with DI support. | `config.di.container`, `agent_actions.errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_*` | Methods | Build runtime components by resolving dependencies before instantiation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_create_with_dependencies` | Method | Unified helper that inspects constructor annotations to supply injected dependencies/overrides. | `inspect`, `typing` |
| `registry` | Instance | Shared `ProcessorRegistry` used across the DI stack. | - |

## Flows

### Container Setup

1. `DIConfigurator.configure_container` registers core services and processors.
2. `ApplicationContainer` wraps the configured container and exposes runner helpers.
3. `ProcessorFactory` + `registry` produce processors, loaders, and generators used by `AgentRunner`.

### Testing

- `DIConfigurator.configure_for_testing` builds a container filled with `unittest.mock` objects.
- `ApplicationContainer.create_for_testing` reuses that container plus mocked profiles.
