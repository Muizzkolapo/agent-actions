# Logging Architecture

agent-actions uses an event-based logging architecture providing both user-friendly CLI output and detailed structured logs for debugging and analytics.

## Overview

The logging system has two primary goals:

1. **User-facing output** - Clean, formatted progress messages during workflow execution
2. **Structured logs** - Complete execution trace for debugging, analytics, and integration

All logging flows through a central EventManager that dispatches events to registered handlers.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                  Application Code                        │
│                                                           │
│  ┌──────────────────┐      ┌──────────────────┐         │
│  │  logger.info()   │      │  fire_event()    │         │
│  │  logger.error()  │      │  (Direct events) │         │
│  └────────┬─────────┘      └────────┬─────────┘         │
│           │                         │                    │
└───────────┼─────────────────────────┼────────────────────┘
            │                         │
            ▼                         │
  ┌──────────────────┐                │
  │ LoggingBridge    │                │
  │ Handler          │                │
  │ (converts to     │                │
  │  events)         │                │
  └────────┬─────────┘                │
           │                         │
           └─────────────┬───────────┘
                         ▼
              ┌──────────────────┐
              │  EventManager    │
              │  (singleton)     │
              │                  │
              │  - Enriches with │
              │    context       │
              │  - Routes by     │
              │    category      │
              └────────┬─────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
    ┌─────────┐  ┌─────────┐  ┌──────────────┐
    │Console  │  │JSON File│  │RunResults    │
    │Handler  │  │Handler  │  │Collector     │
    │         │  │         │  │              │
    │Rich CLI │  │events.  │  │run_results.  │
    │Output   │  │json     │  │json          │
    └─────────┘  └─────────┘  └──────────────┘
```

## Core Components

### EventManager

**Location:** `agent_actions/logging/core/manager.py`

The EventManager is a singleton that:
- Receives all events from the application
- Enriches events with correlation context (workflow_name, correlation_id, etc.)
- Routes events to registered handlers
- Manages handler lifecycle

**Key Methods:**
```python
manager = EventManager.get()  # Get singleton instance

# Register handlers
manager.register(handler)

# Set correlation context
manager.set_context(workflow_name="my_workflow", correlation_id="abc123")

# Or use context manager
with manager.context(workflow_name="my_workflow"):
    fire_event(WorkflowStartEvent(...))
```

### Event Types

**Location:** `agent_actions/logging/events/types.py`

Events are dataclasses that represent specific occurrences in the system:

**Event Categories:**
- `workflow` - Workflow lifecycle events
- `action` - Action execution events
- `batch` - Batch job operations
- `validation` - Validation results
- `progress` - Progress updates
- `system` - System-level events

**Common Events:**
- `WorkflowStartEvent` - Workflow execution begins
- `WorkflowCompleteEvent` - Workflow execution completes
- `WorkflowFailedEvent` - Workflow execution fails
- `ActionStartEvent` - Action begins processing
- `ActionCompleteEvent` - Action completes successfully
- `ActionSkipEvent` - Action skipped (guard condition)
- `ActionFailedEvent` - Action fails with error
- `BatchSubmittedEvent` - Batch job submitted
- `BatchCompleteEvent` - Batch job completes
- `ValidationStartEvent` - Validation begins
- `ValidationCompleteEvent` - Validation passes
- `ValidationErrorEvent` - Validation fails

### Handlers

Handlers receive events and perform actions (output to console, write to file, etc.).

#### ConsoleEventHandler

**Location:** `agent_actions/logging/core/handlers/console.py`

Formats events for user-facing CLI output using Rich.

**Features:**
- Color-coded output by event type
- Timestamp display
- Category filtering (show only workflow/action/batch events by default)
- Verbose mode shows all events

**Example Output:**
```
19:40:16 | ▶ WORKFLOW support_resolution started (5 actions, parallel)
19:40:17 | 1/5 START action: extract_raw_qa...
19:40:32 | 1/5 DONE extract_raw_qa (15.23s, 1.2K tokens)
19:40:32 | 2/5 START action: flatten_raw_questions...
19:40:33 | 2/5 DONE flatten_raw_questions (0.12s, tool)
19:42:15 | ✓ WORKFLOW complete (1m 59s, 12.5K tokens, 5 actions)
```

#### JSONFileHandler

**Location:** `agent_actions/logging/core/handlers/json_file.py`

Writes events to a JSON file in NDJSON format (one JSON object per line).

**Features:**
- Buffered writes (configurable buffer size)
- Creates parent directories automatically
- NDJSON format for easy streaming and parsing
- Full event payload with metadata

**Output Location:** `{workflow}/agent_io/target/events.json`

**Example Entry:**
```json
{
  "event_id": "evt_abc123",
  "timestamp": "2024-01-15T19:40:16.123Z",
  "event_type": "workflow_start",
  "category": "workflow",
  "message": "Starting workflow support_resolution",
  "meta": {
    "invocation_id": "run_xyz789",
    "workflow_name": "support_resolution",
    "correlation_id": "corr_def456"
  },
  "data": {
    "agent_count": 5,
    "execution_mode": "parallel"
  }
}
```

#### RunResultsCollector

**Location:** `agent_actions/logging/events/handlers/run_results.py`

Collects workflow execution data and outputs a `run_results.json` artifact.

**Features:**
- Tracks action execution status, timing, and token usage
- Aggregates total token counts
- Records output folders for each action
- Captures error messages and skip reasons

**Output Location:** `{workflow}/agent_io/target/run_results.json`

**Output Schema:**
```json
{
  "metadata": {
    "invocation_id": "run_xyz789",
    "workflow_name": "support_resolution",
    "agent_count": 5,
    "execution_mode": "parallel",
    "started_at": "2024-01-15T19:40:16.000Z",
    "completed_at": "2024-01-15T19:42:15.456Z",
    "elapsed_time": 119.456,
    "status": "success"
  },
  "results": [
    {
      "unique_id": "support_resolution.extract_raw_qa",
      "agent_name": "extract_raw_qa",
      "agent_index": 1,
      "status": "success",
      "execution_time": 15.23,
      "output_folder": "support_resolution/agent_io/target/extract_raw_qa",
      "record_count": 100,
      "tokens": {
        "prompt_tokens": 800,
        "completion_tokens": 400,
        "total_tokens": 1200
      },
      "timing": {
        "started_at": "2024-01-15T19:40:17.000Z",
        "completed_at": "2024-01-15T19:40:32.234Z"
      }
    }
  ],
  "elapsed_time": 119.456,
  "tokens": {
    "prompt_tokens": 10000,
    "completion_tokens": 2500,
    "total_tokens": 12500
  }
}
```

## Event Flow

### 1. Initialization

When a workflow runs, LoggerFactory initializes the logging system:

```python
# In cli/run.py
LoggerFactory.initialize(
    output_dir=agent_folder,  # {workflow}/agent_io
    workflow_name=workflow_name,
    invocation_id=run_id,
    verbose=args.verbose,
    force=True,
)
```

This:
1. Creates EventManager singleton
2. Registers ConsoleEventHandler
3. Registers JSONFileHandler (writes to `{output_dir}/target/events.json`)
4. Registers RunResultsCollector (writes to `{output_dir}/target/run_results.json`)
5. Sets up LoggingBridgeHandler to convert `logger.*` calls to events

### 2. Event Emission

Events can be emitted two ways:

**Direct Events:**
```python
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(
    message="Starting workflow",
    workflow_name="my_workflow",
    agent_count=5,
))
```

**Python Logging (automatically converted to events):**
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Processing item 123")  # Becomes LogEvent
logger.error("Failed to process")   # Becomes LogEvent with ERROR level
```

### 3. Event Enrichment

EventManager automatically enriches events with correlation context:

```python
# Set context once
manager.set_context(
    workflow_name="my_workflow",
    correlation_id="abc123",
    agent_name="extract_data",
)

# All events inherit this context
fire_event(AgentStartEvent(message="Starting"))
# Event will have workflow_name, correlation_id, agent_name populated
```

### 4. Handler Dispatch

EventManager routes events to handlers based on acceptance criteria:

```python
class ConsoleEventHandler:
    def accepts(self, event: BaseEvent) -> bool:
        # Accept only specific categories
        return event.category in self.categories

    def handle(self, event: BaseEvent) -> None:
        # Format and print event
        self.console.print(self.formatter.format(event))
```

### 5. Output Generation

Handlers process events and generate output:
- **ConsoleHandler** → Rich-formatted terminal output
- **JSONFileHandler** → Append to `events.json`
- **RunResultsCollector** → Aggregate data, write `run_results.json` on flush

## Context Propagation

Context is automatically propagated through nested workflow executions:

```python
# In dependency.py (upstream workflow execution)
with manager.context(
    workflow_name=upstream_name,
    correlation_id=str(uuid4())[:8]
):
    # Execute upstream workflow
    # All events in this scope inherit the context
    upstream_wf.run()

# Context automatically restores after block
```

This ensures proper attribution of events to the correct workflow in the execution hierarchy.

## Testing

### Testing Event Emission

```python
from agent_actions.logging.core.manager import EventManager
from agent_actions.logging.events import WorkflowStartEvent

def test_workflow_event():
    manager = EventManager.get()
    events = []

    # Register test handler
    def capture(event):
        events.append(event)

    manager.register_function(capture)

    # Fire event
    fire_event(WorkflowStartEvent(
        message="Test",
        workflow_name="test",
    ))

    # Verify
    assert len(events) == 1
    assert events[0].workflow_name == "test"
```

### Testing Handlers

```python
from agent_actions.logging.core.handlers import ConsoleEventHandler
from agent_actions.logging.events import AgentCompleteEvent

def test_console_handler():
    handler = ConsoleEventHandler(categories={"agent"})

    event = AgentCompleteEvent(
        message="Completed",
        agent_name="test",
        execution_time=1.5,
    )

    # Test acceptance
    assert handler.accepts(event) is True

    # Test handling (use mock console to capture output)
    handler.handle(event)
```

## Configuration

### Logging Levels

Console verbosity can be controlled:

```bash
# Default: INFO level, workflow/agent/batch categories
agac run

# Verbose: DEBUG level, all categories
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run

# Quiet: WARN level and above (coming in next release)
agac run --quiet
```

### File Handler

File handler writes to:
- `{workflow}/agent_io/target/events.json` (when output_dir is set)
- `logs/agent_actions.log` (fallback, if configured)

Configure via environment or `LoggingConfig`:

```python
from agent_actions.logging.config import LoggingConfig

config = LoggingConfig(
    default_level="INFO",
    file_handler=FileHandlerConfig(
        enabled=True,
        path="logs/events.json",
    ),
)

LoggerFactory.initialize(config=config)
```

## Best Practices

### 1. Use Typed Events

Don't use BaseEvent directly. Create specific event classes:

```python
# Good
fire_event(AgentCompleteEvent(
    message="Agent completed",
    agent_name="extract_data",
    execution_time=15.2,
))

# Bad
fire_event(BaseEvent(
    message="Agent completed",
    category="agent",
    event_type="agent_complete",
))
```

### 2. Clear Messages

Event messages should be human-readable and actionable:

```python
# Good
message="Agent extract_data completed in 15.2s"

# Bad
message="done"
```

### 3. Structured Data

Put machine-readable data in the `data` dict:

```python
fire_event(AgentCompleteEvent(
    message="Agent completed",
    agent_name="extract_data",
    execution_time=15.2,
    tokens={"prompt": 800, "completion": 400},
))
```

The `data` dict will contain:
```json
{
  "agent_name": "extract_data",
  "execution_time": 15.2,
  "tokens": {"prompt": 800, "completion": 400}
}
```

### 4. Use Context Managers

For nested execution contexts:

```python
with manager.context(workflow_name="upstream"):
    # All events here get workflow_name="upstream"
    execute_upstream()

# Context automatically restores
```

### 5. Flush Before Exit

Always flush handlers before exiting:

```python
try:
    run_workflow()
finally:
    LoggerFactory.flush()  # Ensure all buffered events are written
```

## Migration from Legacy Logging

The event system replaces several legacy components:

### ServiceLogger (Deprecated)

**Before:**
```python
from agent_actions.cli.utils.service_logger import ServiceLogger

logger = ServiceLogger()
logger.print("Processing item", style="info")
```

**After:**
```python
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import ProgressEvent

fire_event(ProgressEvent(
    message="Processing item",
    current=1,
    total=100,
))
```

### Direct console.print() (Avoid)

**Before:**
```python
console.print("[green]✓[/green] Completed")
```

**After:**
```python
fire_event(AgentCompleteEvent(
    message="Agent completed",
    agent_name="my_agent",
))
```

The ConsoleEventHandler will format it appropriately.

## Performance Considerations

### Buffering

JSONFileHandler buffers events before writing:

```python
json_handler = JSONFileHandler(
    file_path=log_file,
    buffer_size=10,  # Write every 10 events
)
```

### Handler Acceptance

Handlers filter events early to avoid unnecessary processing:

```python
def accepts(self, event: BaseEvent) -> bool:
    # Quick check before handle() is called
    return event.category in self.categories
```

### Context Copying

EventManager copies context to avoid mutation issues:

```python
# Context is copied to each event
event.meta.invocation_id = self._context["invocation_id"]
event.meta.workflow_name = self._context["workflow_name"]
```

## See Also

- [API Reference](../../api/logging.md) - Detailed API documentation
