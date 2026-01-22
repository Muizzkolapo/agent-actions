# TICKET-002: Create Core Event Handlers

**Status:** ✅ COMPLETED
**Priority:** Critical
**Completed:** January 2026
**Estimate:** 3-4 hours
**Actual:** ~3 hours
**Labels:** logging, handlers, infrastructure

## Description

Create the core event handlers that process events and output them to various destinations. These handlers are reusable and have no agent-actions domain dependencies.

## Deliverables

- [x] `ConsoleEventHandler` - dbt-style Rich console output
- [x] `JSONFileHandler` - NDJSON file logging
- [x] `StructuredLogHandler` - ELK/Datadog compatible output
- [x] `LoggingBridgeHandler` - Converts Python logging to events

## Files Created

```
agent_actions/logging/core/handlers/
├── __init__.py
├── console.py        # ConsoleEventHandler with Rich formatting
├── json_file.py      # JSONFileHandler for NDJSON output
├── structured.py     # StructuredLogHandler for log aggregation
└── bridge.py         # LoggingBridgeHandler + LogEvent, DebugEvent, SystemEvent
```

## ConsoleEventHandler Features

- dbt-style timestamp + message format
- Color-coded status indicators (OK=green, SKIP=yellow, ERROR=red)
- Configurable minimum level
- Category filtering (only show workflow/agent/batch by default)
- Custom formatter support

## JSONFileHandler Features

- NDJSON format (one JSON object per line)
- Buffered writes for performance
- Optional file rotation by size
- Thread-safe
- Auto-creates directories

## LoggingBridgeHandler Features

- Converts Python `logging.LogRecord` to `LogEvent`
- Extracts category from logger name
- Preserves source file/line info
- Auto-registers with EventManager

## Example Output

**Console:**
```
10:30:45 | Running workflow my_workflow (5 agents)
10:30:46 | 1/5 START extract_data
10:30:58 | 1/5 OK extract_data in 12.34s (1700 tokens)
```

**JSON File:**
```json
{"event_type": "WorkflowStartEvent", "code": "W001", "level": "info", ...}
```

## Notes

- Console handler uses Rich for colors (falls back to plain if unavailable)
- JSON handler buffers events for performance (configurable buffer_size)
- Bridge handler enables gradual migration - existing logger.* calls work
