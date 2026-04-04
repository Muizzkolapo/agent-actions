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

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `LoggingConfig.from_project_config()` | `agent_actions.yml` | Reads | `logging.level`, `logging.file.*`, `logging.module_levels`, `logging.include_timestamps`, `logging.include_source_location` |
| `LoggingConfig.from_environment()` | `.env` | Reads | `AGENT_ACTIONS_DEBUG`, `AGENT_ACTIONS_LOG_LEVEL`, `AGENT_ACTIONS_LOG_FORMAT`, `AGENT_ACTIONS_LOG_FILE`, `AGENT_ACTIONS_LOG_DIR`, `AGENT_ACTIONS_NO_LOG_FILE`, `AGENT_ACTIONS_FILE_LOG_LEVEL` |
| `LoggerFactory.initialize()` | `agent_io/target/events.json` | Writes | — |
| `LoggerFactory.initialize()` | `agent_io/target/errors.json` | Writes | — |
| `LoggerFactory._get_log_file_path()` | `logs/events.json` | Writes | `logging.file.path` |
| `RunResultsCollector.flush()` | `agent_io/target/run_results.json` | Writes | — |
| `RedactingFilter.filter()` | `agent_io/target/events.json` | Transforms | — |

**Internal only**: `JSONFormatter`, `ConsoleEventHandler`, `LoggingBridgeHandler`, `EventManager`, `fire_event()` — no direct project surface (internal plumbing between handlers).

**Examples** — see this module in action:
- [`examples/support_resolution/agent_actions.yml`](../../examples/support_resolution/agent_actions.yml) — project config read by `LoggingConfig.from_project_config()`; `model_vendor: ollama` triggers logging of LLM events
- [`examples/support_resolution/.env.example`](../../examples/support_resolution/.env.example) — environment file loaded before `LoggingConfig.from_environment()` runs
- [`examples/book_catalog_enrichment/agent_actions.yml`](../../examples/book_catalog_enrichment/agent_actions.yml) — project config with `output_storage: sqlite`, exercising the `events.json` and `errors.json` file handlers
- [`examples/incident_triage/agent_actions.yml`](../../examples/incident_triage/agent_actions.yml) — multi-action workflow generating `run_results.json` via `RunResultsCollector`
