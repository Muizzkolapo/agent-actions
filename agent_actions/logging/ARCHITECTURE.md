# Logging Module Architecture

This document maps the moving parts of `agent_actions/logging/` -- the module that handles all structured logging, event dispatch, console output, JSON file logging, run-results collection, redaction, and user-facing error translation.

---

## High-Level Overview

```
                       agent_actions/logging/
                              |
           +------------------+------------------+
           |                  |                  |
         core/             events/            errors/
    (dispatch engine)   (event library)   (error translation)
           |                  |                  |
    +------+------+     70+ event types    formatter chain
    |      |      |     across 8 modules   -> UserError
 manager  handlers protocols
(singleton) (4 types) (EventHandler,
                       EventFilter)

Top-level files:
  factory.py    -- LoggerFactory: wires everything together
  config.py     -- LoggingConfig / FileHandlerSettings dataclasses
  filters.py    -- RedactingFilter (stdlib logging layer)
  formatters.py -- JSONFormatter (stdlib logging layer)
```

The module has **three packages** and **four top-level files**:

| Package / File | What it does |
|----------------|-------------|
| `core/` | Singleton EventManager, handler protocols, and the four built-in handler implementations (Console, JSONFile, LoggingBridge, ContextDebug) |
| `events/` | 106 concrete event dataclasses organized by domain (workflow, batch, LLM, validation, etc.) plus the AgentActionsFormatter for console display |
| `errors/` | ErrorTranslator with a chain of 10 formatter strategies that convert any Python exception into a structured UserError for CLI display |
| `factory.py` | LoggerFactory -- the single entry point that initializes EventManager, registers handlers, and wires the stdlib logging bridge |
| `config.py` | LoggingConfig and FileHandlerSettings dataclasses, built from `agent_actions.yml` or `AGENT_ACTIONS_*` env vars |
| `filters.py` | RedactingFilter for the stdlib logging layer -- regex-based scrubbing of API keys, tokens, secrets |
| `formatters.py` | JSONFormatter for stdlib log records (used by legacy code paths, not the primary event system) |

---

## Initialization Flow

Everything starts with `LoggerFactory.initialize()`, typically called by the CLI layer before any workflow runs.

```
LoggerFactory.initialize(config, output_dir, workflow_name, verbose, quiet)
     |
     +-- 1. Build LoggingConfig (from_environment() or from_project_config())
     |
     +-- 2. Get EventManager singleton (EventManager.get())
     |
     +-- 3. _register_handlers():
     |       |
     |       +-- Set context (invocation_id, workflow_name)
     |       |
     |       +-- ConsoleEventHandler
     |       |     min_level from verbose/quiet/config
     |       |     categories: {"workflow", "agent", "batch"} unless verbose
     |       |     formatter: AgentActionsFormatter (Rich color output)
     |       |
     |       +-- JSONFileHandler (events.json) -- all levels, buffer_size=5
     |       |     only when output_dir is provided
     |       |
     |       +-- JSONFileHandler (errors.json) -- ERROR only, buffer_size=1
     |       |     only when output_dir is provided
     |       |
     |       +-- RunResultsCollector
     |             collects workflow/action events -> run_results.json
     |
     +-- 4. _setup_logging_bridge():
     |       |
     |       +-- Attach LoggingBridgeHandler to "agent_actions" root logger
     |       +-- Set root logger to DEBUG (handlers filter by level)
     |       +-- Disable propagation
     |
     +-- 5. manager.initialize() -- marks system ready
     |
     +-- Return EventManager
```

On `force` re-initialization (e.g., when the CLI starts a new workflow in the same process), handlers are flushed and replaced atomically. If handler registration fails, previous handlers are restored.

---

## Two-Tier Logging

The system has two separate entry points for log messages, and they converge in the EventManager.

```
Tier 1: Direct Event API              Tier 2: stdlib logging (bridge)
================================       ================================

fire_event(LLMRequestEvent(...))       logger.info("Submitting batch")
         |                                        |
         v                                        v
  EventManager.fire()                  LoggingBridgeHandler.emit()
         |                               |
         |                               +-- Converts LogRecord -> LogEvent
         |                               |     level: logging.INFO -> EventLevel.INFO
         |                               |     category: extracted from logger name
         |                               |       "agent_actions.workflow.x" -> "workflow"
         |                               |
         |                               +-- EventManager.fire(LogEvent)
         |                                        |
         +----------------------------------------+
         |
         v
  EventManager dispatch loop
    1. Inject context (invocation_id, correlation_id, extras)
    2. Run global filters (if any)
    3. For each handler:
         handler.accepts(event)? -> handler.handle(event)
```

**When to use which tier:**

- **Tier 1 (direct events):** Structured domain events with typed fields and event codes. Used by workflow engine, batch processing, LLM providers, validation.
- **Tier 2 (stdlib bridge):** Traditional `logger.info("message")` calls. Used by lower-level modules and third-party code under the `agent_actions` namespace. These become `LogEvent` instances with code `X000`.

---

## EventManager Dispatch

The EventManager is a **singleton** obtained via `EventManager.get()`. All event routing passes through it.

```
EventManager (singleton, thread-safe)
  |
  +-- _handlers: list[EventHandler]      -- registered in order
  +-- _filters: list[EventFilter]        -- global pre-dispatch filters
  +-- _context: dict[str, Any]           -- shared context (invocation_id, etc.)
  +-- _context_overlay: ContextVar       -- per-thread/coroutine overlay
  +-- _fire_lock: RLock                  -- serializes fire() calls
  |
  fire(event):
    1. Snapshot handlers + filters under lock
    2. Inject context into event.meta
         invocation_id, correlation_id -> direct fields
         everything else -> event.meta.extra
    3. Run filters in order (filter can transform or drop event)
    4. For each handler:
         handler.accepts(event)? -> handler.handle(event)
         Handler exceptions are caught and logged to stderr
         (via non-propagating _stdlib_logger to avoid re-entry)
```

**Context management:**

- `set_context(**kwargs)` sets global context values (invocation_id, workflow_name).
- `context(**kwargs)` provides a thread-local overlay via `ContextVar`, nestable with `with` blocks.
- `_effective_context()` merges global + overlay, with overlay winning on collision.

**Lifecycle:**

- `atexit` callback flushes all handlers at interpreter exit.
- `reset()` clears everything (used in tests).

---

## Event System

All events inherit from `BaseEvent`:

```
@dataclass
BaseEvent
  level: EventLevel     -- DEBUG, INFO, WARN, ERROR
  category: str         -- "workflow", "batch", "llm", etc.
  message: str          -- human-readable description
  meta: EventMeta       -- timestamp, correlation_id, invocation_id, extra
  data: dict[str, Any]  -- structured payload
  |
  event_type -> class name (e.g., "LLMRequestEvent")
  code       -> short prefix + number (e.g., "L001")
  to_dict()  -> full JSON-serializable representation
```

### Event Code Prefixes

Each domain gets a letter prefix. The code is the primary stable identifier for tooling and filtering.

| Prefix | Domain | Example |
|--------|--------|---------|
| W | Workflow lifecycle | W001 WorkflowStartEvent |
| A | Action execution | A001 ActionStartEvent |
| B | Batch processing | B001 BatchSubmittedEvent |
| L | LLM interaction | L001 LLMRequestEvent |
| V | Validation | V001 ValidationStartEvent |
| C | Cache | C001 CacheHitEvent |
| T | Template rendering | T001 TemplateRenderingFailedEvent |
| D | Data loading/parsing | D001 DataParsingErrorEvent |
| G | Guard evaluation | G001 GuardEvaluationErrorEvent |
| R | Recovery/retry | R001 RetryExhaustedEvent |
| F | Configuration | F001 ConfigLoadStartEvent |
| E | Environment | E001 EnvironmentLoadStartEvent |
| I | Initialization/CLI | I001 CLIInitStartEvent |
| P | Plugin/UDF discovery | P001 UDFDiscoveryStartEvent |
| RP | Record processing | RP01 RecordProcessingStartedEvent |
| BP | Batch data processing | BP01 BatchProcessingStartedEvent |
| FIO | File I/O | FIO1 FileWriteStartedEvent |
| DV | Data validation | DV01 DataValidationStartedEvent |
| SO | Schema operations | SO01 SchemaConstructionStartedEvent |
| DT | Data transformation | DT01 EnrichmentPipelineStartedEvent |
| RC | Result collection | RC01 ResultCollectionStartedEvent |
| CX | Context introspection | CX01 ContextNamespaceLoadedEvent |
| X | Bridged log records | X000 LogEvent (from stdlib bridge) |

Event types are spread across 8 source files in `events/`:

| File | Domain | Count (approx.) |
|------|--------|-----------------|
| `workflow_events.py` | Workflow + action lifecycle | 8 |
| `batch_events.py` | Batch submission, polling, completion | 12 |
| `llm_events.py` | LLM requests, responses, errors | 9 |
| `validation_events.py` | Validation, recovery, guard | 14 |
| `initialization_events.py` | CLI, config, env, project, UDF | 21 |
| `io_events.py` | File I/O, schema, context | 13 |
| `data_pipeline_events.py` | Record processing, enrichment, results | 18 |
| `cache_events.py` | Cache hit/miss/invalidation | 6 |

All 106 event types are re-exported from `events/__init__.py`.

---

## Registered Handlers

Four handler types are registered during initialization. Each implements the `EventHandler` protocol: `accepts(event) -> bool`, `handle(event)`, `flush()`, `close()`.

### ConsoleEventHandler

```
Purpose:  User-facing terminal output via Rich (or plain stderr fallback)
Filter:   min_level (verbose=DEBUG, quiet=WARN, default=INFO)
          + category filter: {"workflow", "agent", "batch"} unless verbose
          WARN and ERROR bypass category filter -- always shown
Format:   AgentActionsFormatter dispatch table for known event types,
          _format_default for everything else
Output:   Rich Console(stderr=True) or print(file=sys.stderr)
```

The `AgentActionsFormatter` has a dispatch table for 10 known event types (WorkflowStart, ActionComplete, BatchSubmitted, etc.) with structured formatting. Unknown event types fall through to `_format_default` which just prints the message.

### JSONFileHandler

```
Purpose:  Persistent NDJSON log of all events
Instances: events.json (all levels, buffer=5) + errors.json (ERROR only, buffer=1)
Filter:   min_level only
Buffering: Accumulates events in memory, flushes to disk when buffer fills
           or when flush() is called (atexit, workflow complete, force re-init)
Rotation:  Optional max_file_size with timestamp-based rotation
Thread:    Internal threading.Lock protects buffer and file handle
```

### RunResultsCollector

```
Purpose:  Builds run_results.json summarizing workflow execution
Filter:   category in ("workflow", "action") OR event_type in
          ("RecordEmptyOutputEvent", "ResultCollectionCompleteEvent")
State:    Accumulates ActionResult dataclasses keyed by action_name
Output:   atomic_json_write to {output_dir}/target/run_results.json
          Written on WorkflowComplete/WorkflowFailed events
Tracks:   Per-action: status, timing, record count, token usage,
          empty outputs, guard stats
          Aggregate: total tokens, workflow elapsed time, overall status
```

### LoggingBridgeHandler

```
Purpose:  Routes stdlib logger.info/warning/error calls into EventManager
Attached: To the "agent_actions" root logger (propagation disabled)
Converts: logging.LogRecord -> LogEvent (code X000, category from logger name)
Safety:   Catches all exceptions in emit() -- falls back to handleError()
```

### ContextDebugHandler (optional)

```
Purpose:  Aggregates context introspection events for --debug-context display
Enabled:  Only when LoggerFactory.enable_context_debug() is called
Filter:   Event codes CX001-CX006
Output:   Rich tree display or plain text summary on demand
```

---

## Redaction System

Two independent layers ensure sensitive data does not appear in logs.

### Layer 1: RedactingFilter (stdlib logging)

Attached as a `logging.Filter` on stdlib log records before they reach the bridge. Scrubs:

- Key-value patterns: `api_key=...`, `secret=...`, `token=...`, `password=...`
- Vendor key patterns: `sk-ant-*` (Anthropic), `sk-*` (OpenAI), `AIza*` (Google)
- Extra fields on LogRecord: dict/list values recursively redacted, string values pattern-matched

### Layer 2: `_redact_sensitive_data()` (event data)

Standalone function in `filters.py` used by code that builds event data dicts directly. Recursively walks nested structures and redacts:

- Dict keys matching: `api_key`, `key`, `token`, `password`, `secret`, `authorization`
- String values matching vendor key regex patterns

Both layers use the same regex patterns but operate at different stages -- Layer 1 on stdlib LogRecords, Layer 2 on event data dicts before they reach handlers.

---

## Error Translation

The `errors/` package converts raw Python exceptions into structured, user-friendly CLI messages.

```
Exception (any type)
     |
     v
format_user_error(exc, context)          -- errors/__init__.py
     |
     +-- Debug logging of exception chain
     |
     v
ErrorTranslator.translate(exc, context)  -- errors/translator.py
     |
     +-- ErrorContextService.merge_exception_context()
     |     Extracts context from exception attributes
     |
     +-- extract_root_cause(exc)
     |     Walks __cause__ / __context__ chain
     |
     +-- Formatter chain (first match wins):
     |     1. YAMLSyntaxErrorFormatter    -- YAML parse errors
     |     2. UDFLoadErrorFormatter       -- UDF discovery/import failures
     |     3. FunctionNotFoundFormatter   -- missing UDF functions
     |     4. TemplateErrorFormatter      -- Jinja2 template errors
     |     5. ConfigurationErrorFormatter -- config validation
     |     6. ModelErrorFormatter         -- LLM model errors
     |     7. AuthenticationErrorFormatter -- API key issues
     |     8. FileErrorFormatter          -- file not found, permissions
     |     9. APIErrorFormatter           -- vendor API errors
     |    10. GenericErrorFormatter       -- fallback (always matches)
     |
     v
UserError(category, title, details, fix, context, docs_url)
     |
     v
UserError.format_for_cli() -> str
     |
     +-- "Category: Title"
     +-- "  Problem: ..."
     +-- "  Agent: ... / File: ... / Field: ..."   (priority context)
     +-- "  Fix: ..."
     +-- "  Learn more: ..."
```

Each formatter implements `can_handle(exc, root_cause, message) -> bool` and `format(...) -> UserError`. The chain is ordered from most specific to least specific, with `GenericErrorFormatter` as the guaranteed fallback.

---

## File Index

### Top-level
| File | Role |
|------|------|
| `factory.py` | LoggerFactory -- single entry point, handler registration, bridge setup |
| `config.py` | LoggingConfig + FileHandlerSettings dataclasses |
| `filters.py` | RedactingFilter + `_redact_sensitive_data()` |
| `formatters.py` | JSONFormatter for stdlib LogRecords |

### core/
| File | Role |
|------|------|
| `core/manager.py` | EventManager singleton -- thread-safe dispatch, context management |
| `core/events.py` | BaseEvent, EventLevel, EventCategory, EventMeta |
| `core/protocols.py` | EventHandler / EventFilter protocols, LevelFilter, CategoryFilter |
| `core/handlers/bridge.py` | LoggingBridgeHandler + LogEvent, DebugEvent, SystemEvent |
| `core/handlers/console.py` | ConsoleEventHandler -- Rich or plain stderr output |
| `core/handlers/json_file.py` | JSONFileHandler -- buffered NDJSON writer with rotation |
| `core/handlers/context_debug.py` | ContextDebugHandler -- aggregates CX events for debug display |

### events/
| File | Role |
|------|------|
| `events/__init__.py` | Re-exports all 106 event types + AgentActionsFormatter |
| `events/types.py` | EventCategories constants + `_safe_value_repr()` |
| `events/formatters.py` | AgentActionsFormatter -- dispatch table for console display |
| `events/workflow_events.py` | W/A prefix events (workflow + action lifecycle) |
| `events/batch_events.py` | B prefix events (batch submission, polling, completion) |
| `events/llm_events.py` | L prefix events (LLM request/response/error) |
| `events/validation_events.py` | V/G/R prefix events (validation, guard, recovery) |
| `events/initialization_events.py` | F/E/I/P prefix events (config, env, CLI, UDF) |
| `events/io_events.py` | FIO/SO/CX prefix events (file I/O, schema, context) |
| `events/data_pipeline_events.py` | RP/BP/DV/DT/RC prefix events (record processing, enrichment, results) |
| `events/cache_events.py` | C prefix events (cache hit/miss/invalidation) |
| `events/handlers/run_results.py` | RunResultsCollector + ActionResult |

### errors/
| File | Role |
|------|------|
| `errors/__init__.py` | `format_user_error()` entry point |
| `errors/translator.py` | ErrorTranslator -- formatter chain dispatch |
| `errors/user_error.py` | UserError dataclass + `format_for_cli()` |
| `errors/services/` | ErrorContextService -- extracts context from exceptions |
| `errors/formatters/` | 10 formatter strategies (YAML, UDF load, config, model, auth, file, API, template, function, generic) |

---

## Caveats

**Event codes are public API.** External tooling, the ContextDebugHandler, and RunResultsCollector all match on event codes and event_type strings. Changing a code prefix or renaming an event class is a breaking change.

**RunResultsCollector matches by string.** The `accepts()` method checks `event.event_type` (class name as string) for `RecordEmptyOutputEvent` and `ResultCollectionCompleteEvent`. The `handle()` method dispatches on `event_type` strings in a long if/elif chain. Renaming an event class silently breaks result collection.

**Bridge re-entry prevention.** The EventManager's internal `_stdlib_logger` has `propagate = False` to avoid a cycle: if a handler raises during `fire()`, the warning log must not re-enter `fire()` through the LoggingBridgeHandler. Similarly, `LoggingBridgeHandler.emit()` catches all exceptions to prevent bridge errors from propagating.

**Category bypass for WARN/ERROR.** The ConsoleEventHandler always shows WARN and ERROR events regardless of the category filter. This means errors from modules outside the configured categories (e.g., `llm`, `processing`) are still visible on the console. This is intentional -- errors must not be silently hidden by category filtering.

**JSONFileHandler buffering.** Events are buffered in memory (default buffer_size=5 for events.json, 1 for errors.json) and only flushed to disk when the buffer fills, when `flush()` is called, or at interpreter exit via `atexit`. A crash between buffer fills loses buffered events. The errors.json handler uses buffer_size=1 to minimize this risk for error events.

**Force re-init atomicity.** When `initialize(force=True)` is called, existing handlers are stashed before new ones are registered. If registration fails, stashed handlers are restored. This prevents the logging system from being left in a degraded state during re-initialization (e.g., when switching workflows in the same process).
