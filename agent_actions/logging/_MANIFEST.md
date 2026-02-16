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
