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
| `FileHandlerSettings` | Class | File handler configuration used by the factory. | `logging` |
| `LoggingConfig` | Class | Central logging configuration builder with `from_project_config`/`from_environment`. | `logging` |
| `factory.py` | Module | `LoggerFactory` that wires together configuration, filters, and handlers. Always registers Console; `events.json` (all levels) and `errors.json` (ERROR-only) attach only when `initialize()` is given `output_dir` (i.e. an actual workflow run — `agac run`/`agac retry`), so a command that isn't running a workflow writes no file. On init, clamps noisy third-party SDK/HTTP loggers (httpx, urllib3, openai, anthropic, ollama, groq, cohere, google_genai, googleapiclient, etc.) to WARNING and applies user-supplied `logging.module_levels` overrides; pre-init levels are snapshotted and restored by `reset()`. Remembers the console verbosity the CLI flags asked for, so a `force=True` re-init that omits `verbose`/`quiet` preserves it. | `logging` |
| `LoggerFactory` | Class | Manages logger creation, third-party suppression, and the `events.json` bridge. | `logging` |
| `diagnostics.py` | Module | `DIAGNOSTIC` marker passed as `extra=` on log calls describing framework mechanics: dropped by the console unless the run is verbose, kept at full level by the JSON handlers. | `logging` |
| `filters.py` | Module | Custom filters (e.g., `RedactingFilter`) to sanitize sensitive payloads. | `logging` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `LoggingConfig.from_project_config()` | `agent_actions.yml` | Reads (not wired into CLI yet — programmatic only) | `logging`, `logging.level`, `logging.file`, `logging.module_levels` |
| `LoggingConfig.from_environment()` | `.env` | Reads | `AGENT_ACTIONS_DEBUG`, `AGENT_ACTIONS_LOG_LEVEL`, `AGENT_ACTIONS_LOG_FORMAT`, `AGENT_ACTIONS_LOG_DIR` |
| `LoggerFactory.initialize(output_dir=...)` | `{output_dir}/logs/events.json` | Writes (run only) | — |
| `LoggerFactory.initialize(output_dir=...)` | `{output_dir}/logs/errors.json` | Writes (run only) | — |
| `RunResultsCollector` | `agent_io/target/run_results.json` | Writes | — |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `cli` | inbound | CLI initializes LoggerFactory and fires lifecycle events |
| `workflow` | inbound | Workflow executor emits structured events during runs |
| `errors` | outbound | Translates internal errors into user-facing log messages |
