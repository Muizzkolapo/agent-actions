# Logging Manifest

**[> Architecture Deep Dive (ARCHITECTURE.md)](ARCHITECTURE.md)**

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
| `FileHandlerSettings` | Class | File handler configuration used by the factory: `max_bytes` (DEBUG cap per run file, `AGENT_ACTIONS_LOG_MAX_BYTES`) and `backup_count` (earlier runs kept, `AGENT_ACTIONS_LOG_RETAIN_RUNS`). | `logging` |
| `LoggingConfig` | Class | Central logging configuration builder with `from_project_config`/`from_environment`. | `logging` |
| `valid_module_levels` | Function | Returns the `module_levels` entries a logger can take (str key outside `agent_actions`, valid level, normalized) and reports each other one on stderr; called by `from_project_config` (so the CLI reports a bad entry once) and by the factory on every init. | `logging` |
| `factory.py` | Module | `LoggerFactory` that wires together configuration, filters, and handlers. Always registers Console; `events.json` (all levels) and `errors.json` (ERROR-only) attach only when `initialize()` is given `output_dir` (i.e. an actual workflow run — `agac run`/`agac retry`), so a command that isn't running a workflow writes no file. `initialize(new_run=True)` (`agac run`/`agac retry` only) first rotates both files to `.1.json` … `.N.json`, so `events.json` holds one run; other commands append to it. On init, clamps noisy third-party SDK/HTTP loggers (httpx, urllib3, openai, anthropic, ollama, groq, cohere, google_genai, googleapiclient, etc.) to WARNING and applies user-supplied `logging.module_levels` overrides; pre-init levels are snapshotted and restored by `reset()`. Remembers the console verbosity the CLI flags asked for, so a `force=True` re-init that omits `verbose`/`quiet` preserves it; a re-init that omits `config` keeps the config the CLI resolved (project block + env) rather than rebuilding from env alone. | `logging` |
| `LoggerFactory` | Class | Manages logger creation, third-party suppression, and the `events.json` bridge. | `logging` |
| `diagnostics.py` | Module | `DIAGNOSTIC` marker passed as `extra=` on log calls describing framework mechanics: dropped by the console unless the run is verbose, kept at full level by the JSON handlers. | `logging` |
| `filters.py` | Module | Custom filters (e.g., `RedactingFilter`) to sanitize sensitive payloads by key name and pattern, and by value: `register_secret()` masks a value read at run time (an endpoint's credential) wherever it appears. | `logging` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `LoggingConfig.from_project_config()` | `agent_actions.yml` | Reads at CLI boot (`cli/main.py` `_configure_logging`); reports any key under `logging:` that nothing reads, and drops and reports each invalid `module_levels` entry | `logging.level`, `logging.module_levels`, `logging.file.max_bytes`, `logging.file.backup_count` |
| `LoggingConfig.from_environment(base)` | `.env` | Reads; a set variable overrides the project value in *base* | `AGENT_ACTIONS_DEBUG`, `AGENT_ACTIONS_LOG_LEVEL`, `AGENT_ACTIONS_LOG_MAX_BYTES`, `AGENT_ACTIONS_LOG_RETAIN_RUNS` |
| `report_unread_env_vars()` | `.env` | Reads at CLI boot (`cli/main.py` `_resolve_logging_base`); names each set logging variable nothing reads on stderr | `AGENT_ACTIONS_LOG_FILE`, `AGENT_ACTIONS_LOG_DIR`, `AGENT_ACTIONS_NO_LOG_FILE`, `AGENT_ACTIONS_FILE_LOG_LEVEL`, `AGENT_ACTIONS_LOG_FORMAT` |
| `LoggerFactory.initialize(output_dir=...)` | `{output_dir}/logs/events.json` | Writes (run only) | — |
| `LoggerFactory.initialize(output_dir=...)` | `{output_dir}/logs/errors.json` | Writes (run only) | — |
| `LoggerFactory.initialize(new_run=True)` | `{output_dir}/logs/{events,errors}.N.json` | Renames, deletes past N | — |
| `RunResultsCollector` | `agent_io/target/run_results.json` | Writes | — |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `cli` | inbound | CLI initializes LoggerFactory and fires lifecycle events |
| `workflow` | inbound | Workflow executor emits structured events during runs |
| `errors` | outbound | Translates internal errors into user-facing log messages |
