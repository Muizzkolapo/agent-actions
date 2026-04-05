# Logging Manifest

## Overview

Structured logging helpers for the Agent Actions core—including configuration,
factories, filters, formatters, and the event-driven error/reporting plumbing.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [core](core/_MANIFEST.md) | Logger manager, event protocols, and handler helpers. |
| [errors](errors/_MANIFEST.md) | Error logging utilities, transformers, and formatters. |
| [events](events/_MANIFEST.md) | Event-based logging and telemetry registries. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `config.py` | Module | Dataclasses that capture project logging, handler, and formatting defaults. | `logging` |
| `FileHandlerSettings` | Class | File handler configuration used by the factory. | `logging` |
| `LoggingConfig` | Class | Central logging configuration builder with `from_project_config`/`from_environment`. | `logging` |
| `factory.py` | Module | `LoggerFactory` that wires together configuration, filters, and handlers. Registers four handler types: Console, `events.json` (all levels), `errors.json` (ERROR-only, output_dir runs only), and `run_results.json`. | `logging` |
| `LoggerFactory` | Class | Manage logger creation, level setting, and debug state. | `logging` |
| `filters.py` | Module | Custom filters (e.g., `RedactingFilter`) to sanitize sensitive payloads. | `logging` |
| `formatters.py` | Module | Formatter helpers such as `JSONFormatter` used across services. | `logging` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `LoggingConfig.from_project_config()` | `agent_actions.yml` | Reads | `logging`, `logging.level`, `logging.file` |
| `LoggingConfig.from_environment()` | `.env` | Reads | `AGENT_ACTIONS_DEBUG`, `AGENT_ACTIONS_LOG_LEVEL`, `AGENT_ACTIONS_LOG_FORMAT`, `AGENT_ACTIONS_LOG_DIR` |
| `LoggerFactory.initialize()` | `agent_io/target/events.json` | Writes | — |
| `LoggerFactory.initialize()` | `agent_io/target/errors.json` | Writes | — |
| `RunResultsCollector` | `agent_io/target/run_results.json` | Writes | — |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `cli` | inbound | CLI initializes LoggerFactory and fires lifecycle events |
| `workflow` | inbound | Workflow executor emits structured events during runs |
| `config` | outbound | Reads project root to determine default log file paths |
| `errors` | outbound | Translates internal errors into user-facing log messages |
