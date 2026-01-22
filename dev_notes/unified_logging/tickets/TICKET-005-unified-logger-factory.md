# TICKET-005: Refactor LoggerFactory for Unified Event System

**Status:** ✅ COMPLETED
**Priority:** Critical
**Completed:** January 2026
**Estimate:** 3-4 hours
**Actual:** ~3 hours
**Labels:** logging, refactor, infrastructure

## Description

Refactor `LoggerFactory` to use the event system as the single backend. All Python logging calls are bridged to events, and all output flows through event handlers.

## Deliverables

- [x] Unified `initialize()` method
- [x] Setup `LoggingBridgeHandler` for Python logging
- [x] Register event handlers (console, JSON, run_results)
- [x] Remove old handler creation code
- [x] Backwards compatibility aliases

## File Modified

```
agent_actions/logging/factory.py    # Complete rewrite
```

## New Architecture

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
```

## New API

```python
from agent_actions.logging import LoggerFactory

# Initialize unified system
LoggerFactory.initialize(
    config=None,              # Optional LoggingConfig
    output_dir="/path/out",   # For artifacts
    workflow_name="my_wf",    # Context
    invocation_id="abc123",   # Unique run ID
    verbose=False,            # DEBUG on console
    quiet=False,              # Only WARN+ on console
    force=False,              # Reinitialize
)

# Get logger (works as before)
logger = LoggerFactory.get_logger("my_module")
logger.info("This becomes an event")

# Set context
LoggerFactory.set_context(correlation_id="req-123")

# Flush all handlers
LoggerFactory.flush()
```

## Changes from Old API

| Old | New |
|-----|-----|
| `initialize(config)` | `initialize(config, output_dir, workflow_name, ...)` |
| `initialize_events(...)` | `initialize(...)` (same method now) |
| `flush_events()` | `flush()` |
| `set_event_context(...)` | `set_context(...)` |

## Backwards Compatibility

Aliases provided for old method names:
```python
initialize_events = initialize
set_event_context = set_context
flush_events = flush
```

## What Was Removed

- Direct Python logging handlers (StreamHandler, RotatingFileHandler)
- HumanFormatter, SimpleFormatter usage in factory
- Complex handler configuration logic
- Separate event initialization

## Notes

- LoggingBridgeHandler converts all logger.* calls to LogEvent
- Console only shows workflow/agent/batch by default
- verbose=True shows all event categories
- All output is now event-based
