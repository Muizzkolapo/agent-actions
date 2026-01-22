# Unified Logging System - Technical Overview

**Date:** January 2026
**Status:** Core implementation complete, migration in progress

## Summary

We implemented a **dbt-style centralized logging system** that unifies all logging through a single event-based architecture. This replaces the previous dual-system approach (Python logging + Rich console.print) with a single, consistent infrastructure.

## Problem Statement

The previous logging had several issues:

1. **Two separate systems** - Python `logging` module for file logs and `console.print()` for user output
2. **Inconsistent output** - Debug logs and user messages interleaved
3. **No structured artifacts** - No `run_results.json` for CI/CD integration
4. **Hard to reuse** - Logging code tightly coupled to agent-actions domain

## Solution Architecture

```
                    Application Code
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
    logger.info()    fire_event()     console.print()
          │                │           (deprecated)
          │                │
          ▼                │
  LoggingBridgeHandler     │
          │                │
          └───────►  EventManager  ◄───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        Console       JSON File    run_results.json
        (dbt-style)   (debug)        (artifact)
```

### Key Design Decisions

1. **Event-First Architecture** - All logging flows through typed events
2. **Automatic Bridge** - Existing `logger.*` calls automatically become events via `LoggingBridgeHandler`
3. **Reusable Core** - `logging/core/` has zero agent-actions imports, can be extracted to separate package
4. **dbt-Inspired** - Event codes (W001, A002), clean console output, run_results.json artifact

## File Structure

```
agent_actions/logging/
├── __init__.py                    # Public API exports
├── factory.py                     # LoggerFactory - unified initialization
├── config.py                      # LoggingConfig (unchanged)
├── context.py                     # CorrelationContext (unchanged)
│
├── core/                          # REUSABLE CORE (no agent-actions imports)
│   ├── __init__.py
│   ├── events.py                  # BaseEvent, EventLevel, EventMeta
│   ├── protocols.py               # EventHandler protocol, filters
│   ├── manager.py                 # EventManager singleton, fire_event()
│   └── handlers/
│       ├── __init__.py
│       ├── bridge.py              # LoggingBridgeHandler (Python logging → events)
│       ├── console.py             # ConsoleEventHandler (dbt-style output)
│       ├── json_file.py           # JSONFileHandler (NDJSON logs)
│       └── structured.py          # StructuredLogHandler (ELK/Datadog)
│
└── events/                        # AGENT-ACTIONS SPECIFIC
    ├── __init__.py
    ├── types.py                   # WorkflowEvent, AgentEvent, BatchEvent, etc.
    ├── formatters.py              # AgentActionsFormatter (dbt-style formatting)
    └── handlers/
        ├── __init__.py
        └── run_results.py         # RunResultsCollector (run_results.json)
```

## Event Types

| Code | Event | Category | Description |
|------|-------|----------|-------------|
| W001 | WorkflowStartEvent | workflow | Workflow execution begins |
| W002 | WorkflowCompleteEvent | workflow | Workflow completes successfully |
| W003 | WorkflowFailedEvent | workflow | Workflow fails |
| A001 | AgentStartEvent | agent | Agent starts execution |
| A002 | AgentCompleteEvent | agent | Agent completes successfully |
| A003 | AgentSkipEvent | agent | Agent skipped (cached/condition) |
| A004 | AgentFailedEvent | agent | Agent fails |
| A005 | AgentCachedEvent | agent | Agent result from cache |
| B001 | BatchSubmittedEvent | batch | Batch job submitted |
| B002 | BatchProgressEvent | batch | Batch progress update |
| B003 | BatchCompleteEvent | batch | Batch job complete |
| L001 | LLMRequestEvent | llm | LLM API request |
| L002 | LLMResponseEvent | llm | LLM API response |
| L003 | LLMErrorEvent | llm | LLM API error |
| L004 | RateLimitEvent | llm | Rate limit hit |
| V001-V004 | Validation events | validation | Config validation |
| X001 | DebugEvent | debug | Debug information |
| X002 | SystemEvent | system | System lifecycle |
| X### | LogEvent | log | Bridged Python logging |

## Usage

### Preferred: Typed Events

```python
from agent_actions.logging import fire_event
from agent_actions.logging.events import WorkflowStartEvent, AgentCompleteEvent

fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    agent_count=5,
    execution_mode="parallel",
))

fire_event(AgentCompleteEvent(
    agent_name="extract_data",
    agent_index=0,
    total_agents=5,
    execution_time=12.34,
    tokens={"total_tokens": 1700},
))
```

### Legacy: Python Logging (Auto-Bridged)

```python
from agent_actions.logging import LoggerFactory

logger = LoggerFactory.get_logger("my_module")
logger.info("This becomes a LogEvent")
logger.debug("Debug info goes to JSON file only")
```

### Initialization

```python
from agent_actions.logging import LoggerFactory

# Full initialization with all options
LoggerFactory.initialize(
    output_dir="/path/to/output",     # For run_results.json and events.json
    workflow_name="my_workflow",       # Workflow context
    invocation_id="abc123",            # Unique run ID
    verbose=True,                      # Show DEBUG on console
    quiet=False,                       # Only show WARN+ on console
)
```

## Output Formats

### Console (User-Facing)

```
10:30:45 | Running workflow my_workflow (5 agents)
10:30:46 | 1/5 START extract_data
10:30:58 | 1/5 OK extract_data in 12.34s (1700 tokens)
10:31:00 | 2/5 SKIP transform (already completed)
10:32:08 | Completed in 83.45s | 4 OK | 1 SKIP | 0 ERROR
```

### JSON File (`target/events.json`)

```json
{"event_type": "WorkflowStartEvent", "code": "W001", "level": "info", "category": "workflow", "message": "Running workflow my_workflow (5 agents)", "meta": {"timestamp": "2026-01-22T10:30:45.123Z", "invocation_id": "abc123"}, "data": {"workflow_name": "my_workflow", "agent_count": 5}}
{"event_type": "AgentCompleteEvent", "code": "A002", "level": "info", "category": "agent", ...}
```

### Run Results (`target/run_results.json`)

```json
{
  "metadata": {
    "invocation_id": "abc123",
    "workflow_name": "my_workflow",
    "agent_count": 5,
    "execution_mode": "parallel",
    "started_at": "2026-01-22T10:30:45.123Z",
    "completed_at": "2026-01-22T10:32:08.456Z",
    "elapsed_time": 83.333,
    "status": "success"
  },
  "results": [
    {
      "unique_id": "my_workflow.extract_data",
      "agent_name": "extract_data",
      "agent_index": 0,
      "status": "success",
      "execution_time": 12.34,
      "tokens": {"prompt_tokens": 500, "completion_tokens": 1200, "total_tokens": 1700}
    }
  ],
  "elapsed_time": 83.333,
  "tokens": {"prompt_tokens": 2500, "completion_tokens": 5000, "total_tokens": 7500}
}
```

## What Changed

### Modified Files

| File | Changes |
|------|---------|
| `logging/__init__.py` | Added event system exports |
| `logging/factory.py` | Complete rewrite - unified initialization |
| `workflow/coordinator.py` | Fire workflow/agent events instead of console.print |
| `workflow/executor.py` | Fire skip/batch events |
| `cli/main.py` | Use unified LoggerFactory.initialize() |
| `cli/run.py` | Initialize logging with workflow context |

### New Files

| File | Purpose |
|------|---------|
| `logging/core/events.py` | BaseEvent, EventLevel, EventMeta |
| `logging/core/protocols.py` | EventHandler protocol |
| `logging/core/manager.py` | EventManager singleton |
| `logging/core/handlers/bridge.py` | Python logging → events |
| `logging/core/handlers/console.py` | dbt-style console output |
| `logging/core/handlers/json_file.py` | NDJSON file handler |
| `logging/core/handlers/structured.py` | ELK/Datadog compatible |
| `logging/events/types.py` | All agent-actions event types |
| `logging/events/formatters.py` | dbt-style formatting |
| `logging/events/handlers/run_results.py` | run_results.json collector |

## Migration Status

- [x] Core event infrastructure
- [x] Event handlers (console, JSON, run_results)
- [x] Logging bridge (Python logging → events)
- [x] Workflow coordinator instrumented
- [x] Agent executor instrumented
- [x] CLI integration
- [ ] Remove remaining console.print() calls
- [ ] Add events to LLM providers
- [ ] Add events to batch processing
- [ ] Add events to validation
- [ ] Update tests
- [ ] Documentation

## References

- [dbt Events README](https://github.com/dbt-labs/dbt-core/blob/main/core/dbt/events/README.md)
- [dbt Events and Logging Docs](https://docs.getdbt.com/reference/events-logging)
