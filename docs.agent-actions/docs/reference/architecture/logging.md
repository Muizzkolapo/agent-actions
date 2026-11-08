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
              │  - Dispatches to │
              │    each handler  │
              │    that accepts  │
              │    the event     │
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

**Location:** `agent_actions/logging/events/` holds one module per category of events. `types.py` there holds the category constants, and the base class, `BaseEvent`, lives in `agent_actions/logging/core/events.py`.

Events are dataclasses that represent specific occurrences in the system. The event class name is the `event_type` written to `events.json`:

**Event Categories:**
- `workflow` - Workflow lifecycle events
- `action` - Action execution events
- `batch` - Batch job operations
- `llm` - LLM requests and responses
- `validation` - Validation results
- `cache`, `template`, `data`, `guard`, `recovery` - Cache, template rendering, data loading, guard evaluation and retry events
- `configuration`, `initialization`, `plugin` - Configuration loading, CLI start-up and tool discovery events
- `data_processing`, `file_io`, `schema`, `transformation` - Record pipeline, file, schema and transformation events

An event that sets no category has the category `system`.

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
- Category filtering (workflow, action and batch events by default); warnings and errors show whatever their category
- Verbose mode shows all events
- Drops events marked diagnostic unless the run is verbose

#### ProgressRenderer

**Location:** `agent_actions/logging/core/handlers/progress.py`

The console handler a run installs. It consumes the workflow, step and action
events and renders them as one grouped progress stream: one line per action,
under the dependency step that produced it. Anything it does not recognise falls
through to `ConsoleEventHandler`'s formatting, so warnings and errors from any
module are untouched.

**Example Output:**
```
species_id_cards — 18 actions
Step 1/12 summarize_entry
  ✓ summarize_entry  2 records in 0.4s (agac-provider/gpt-4o-mini)
Step 2/12 3 actions: extract_field_marks_1, extract_field_marks_2, extract_field_marks_3
  ✓ extract_field_marks_1  2 records in 0.1s (agac-provider/gpt-4o-mini)
  ✓ extract_field_marks_2  2 records in 0.1s (agac-provider/gpt-4o-mini)
  ✓ extract_field_marks_3  2 records in 0.1s (agac-provider/gpt-4o-mini)
Step 4/12 flatten_marks
  ✓ flatten_marks  3 records in 0.0s
Step 12/12 2 actions: auto_review_note, describe_confusion_risk
  ○ auto_review_note  skipped — All records guard-filtered — no output produced

✓ 0.6s — 16 completed, 2 skipped
```

An action reports once, on completion; `--verbose` additionally announces each
one as it starts. The record count includes the rows the action's guard skipped, kept
as tombstones; `— N skipped by guard` says how many those are, and is left off when
there are none:

```
  ✓ repaired  4 records in 0.2s (agac-provider/mock) — 1 skipped by guard
```

An action that shipped records with a failing [expectations](../validation/expectations.md) verdict
(`on_exhausted: return_last`, `repair: none`) turns `⚠` (`WARN` without color) and says how
many; the workflow line counts every such record the workflow's actions hold, read from the
store, so a batch workflow finishing over several runs counts what the earlier runs
collected. It turns `⚠` too, unless an action failed, which keeps `✗`. The exit code does not change: gate CI on verdicts with `agac expect report --fail-under`.

```
  ⚠ observed  4 records in 0.1s (agac-provider/mock) — 4 failed their checks
  ⚠ repaired  4 records in 0.1s (agac-provider/mock) — 1 skipped by guard, 3 failed their checks
  ✓ warned  4 records in 0.1s (agac-provider/mock)

⚠ 0.1s — 3 completed, 7 records failed their checks
```

A batch action's duration is marked `(batch)` so provider
queue time does not read as local work.

#### JSONFileHandler

**Location:** `agent_actions/logging/core/handlers/json_file.py`

Writes events to a JSON file in NDJSON format (one JSON object per line).

**Features:**
- Buffered writes (configurable buffer size)
- Creates parent directories automatically
- NDJSON format for easy streaming and parsing
- Full event payload with metadata

**Output Location:** `{workflow}/agent_io/logs/events.json` holds every level. A second handler writes `{workflow}/agent_io/logs/errors.json`, which holds ERROR events only.

**Example Entry** (one line in the file, indented here to read):
```json
{
  "event_type": "WorkflowStartEvent",
  "code": "W001",
  "level": "info",
  "category": "workflow",
  "message": "Running workflow support_resolution (5 actions)",
  "diagnostic": false,
  "meta": {
    "timestamp": "2026-01-15T19:40:16.123456+00:00",
    "correlation_id": "4f8641ff",
    "invocation_id": "run_support_resolution_8535dbc9",
    "thread_id": null,
    "workflow_name": "support_resolution"
  },
  "data": {
    "workflow_name": "support_resolution",
    "action_count": 5,
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

**Output Location:** `{workflow}/agent_io/logs/run_results.json`

**Output Schema:**
```json
{
  "metadata": {
    "invocation_id": "run_support_resolution_8535dbc9",
    "workflow_name": "support_resolution",
    "action_count": 5,
    "execution_mode": "parallel",
    "started_at": "2026-01-15T19:40:16.000000+00:00",
    "completed_at": "2026-01-15T19:42:15.456000+00:00",
    "elapsed_time": 119.456,
    "status": "success"
  },
  "results": [
    {
      "unique_id": "support_resolution.extract_raw_qa",
      "action_name": "extract_raw_qa",
      "action_index": 0,
      "status": "success",
      "execution_time": 15.23,
      "output_folder": "/path/to/project/agent_workflow/support_resolution/agent_io/target/extract_raw_qa",
      "record_count": 100,
      "tokens": {
        "prompt_tokens": 800,
        "completion_tokens": 400,
        "total_tokens": 1200
      },
      "error_message": null,
      "skip_reason": null,
      "empty_output_records": 0,
      "timing": {
        "started_at": "2026-01-15T19:40:17.000000+00:00",
        "completed_at": "2026-01-15T19:40:32.234000+00:00"
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
    workflow_name=self.agent_name,
    invocation_id=run_id,
    force=True,
    new_run=True,  # rotate the earlier run logs first
)
```

This:
1. Creates EventManager singleton
2. Registers ProgressRenderer (the console handler for a run)
3. Registers JSONFileHandler (writes every level to `{output_dir}/logs/events.json`)
4. Registers a second JSONFileHandler (writes ERROR events to `{output_dir}/logs/errors.json`)
5. Registers RunResultsCollector (writes `{output_dir}/logs/run_results.json`)
6. Sets up LoggingBridgeHandler to convert `logger.*` calls to events

### 2. Event Emission

Events can be emitted two ways:

**Direct Events:**
```python
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    action_count=5,
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
)

# All events inherit this context
fire_event(ActionStartEvent(action_name="extract_data"))
# Event will have workflow_name and correlation_id populated
```

### 4. Handler Dispatch

EventManager routes events to handlers based on acceptance criteria:

```python
class ConsoleEventHandler:
    def accepts(self, event: BaseEvent) -> bool:
        # Below the minimum level: refused
        # Diagnostic event on a non-verbose run: refused
        # WARN and ERROR: accepted whatever the category
        # Otherwise: accepted when the category is in self.categories
        ...

    def handle(self, event: BaseEvent) -> None:
        # Format and print event
        ...
```

### 5. Output Generation

Handlers process events and generate output:
- **ConsoleHandler** → Rich-formatted terminal output
- **JSONFileHandler** → Append to `events.json`
- **RunResultsCollector** → Aggregate data, write `run_results.json` on flush

## Context Propagation

`manager.context()` overlays context values for the code inside the block, for each thread and coroutine separately:

```python
with manager.context(workflow_name="upstream", correlation_id="abc123"):
    # All events in this scope inherit the context
    run_upstream()

# Context automatically restores after block
```

This ensures proper attribution of events to the correct workflow or action.

Each action runs inside `manager.context(action_name=..., action_index=...)`, so every event
it fires, from its worker threads too, names it in `meta`. Actions of one step run at once,
which is why the action is never set with `set_context()`: that value is shared by all of them.

## Testing

### Testing Event Emission

```python
from agent_actions.logging.core.manager import EventManager, fire_event
from agent_actions.logging.events import WorkflowStartEvent


class CaptureHandler:
    def __init__(self):
        self.events = []

    def accepts(self, event):
        return True

    def handle(self, event):
        self.events.append(event)

    def flush(self):
        pass

    def close(self):
        pass


def test_workflow_event():
    EventManager.reset()
    manager = EventManager.get()

    # Register test handler
    capture = CaptureHandler()
    manager.register(capture)

    # Fire event
    fire_event(WorkflowStartEvent(workflow_name="test", action_count=1))

    # Verify
    assert len(capture.events) == 1
    assert capture.events[0].data["workflow_name"] == "test"
```

### Testing Handlers

```python
from agent_actions.logging.core.handlers import ConsoleEventHandler
from agent_actions.logging.events import ActionCompleteEvent

def test_console_handler():
    handler = ConsoleEventHandler(categories={"action"})

    event = ActionCompleteEvent(
        action_name="test",
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
# Default: INFO level, workflow/action/batch categories
agac run -a my_workflow

# Verbose: all categories, diagnostic events included
agac --verbose run -a my_workflow

# DEBUG level, same categories as the default
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow

# Quiet: warnings and errors only
agac --quiet run -a my_workflow
```

### File Handler

The file handler only attaches when a workflow run passes `output_dir` to
`LoggerFactory.initialize()` — `agac run`, `agac retry` and the `agac batch` commands do this once the
run's own output directory is known:

```python
LoggerFactory.initialize(output_dir=agent_folder, workflow_name=..., invocation_id=run_id)
```

It writes `{output_dir}/logs/events.json` (all levels) and
`{output_dir}/logs/errors.json` (ERROR level only). A command that isn't
executing a workflow — `agac inspect`, `validate-udfs`, and other read-only
paths — never supplies `output_dir`, so it registers no file handler and
writes nothing to disk.

## Best Practices

### 1. Use Typed Events

Don't use BaseEvent directly. Create specific event classes:

```python
# Good
fire_event(ActionCompleteEvent(
    action_name="extract_data",
    execution_time=15.2,
))

# Bad
fire_event(BaseEvent(
    message="Action completed",
    category="action",
))
```

### 2. Clear Messages

Event messages should be human-readable and actionable:

```python
# Good
message="Action extract_data completed in 15.2s"

# Bad
message="done"
```

### 3. Structured Data

Put machine-readable data in the `data` dict:

```python
fire_event(ActionCompleteEvent(
    action_name="extract_data",
    execution_time=15.2,
    tokens={"prompt_tokens": 800, "completion_tokens": 400, "total_tokens": 1200},
))
```

The event class builds the `message` and the `data` dict from its fields. The `data` dict will contain:
```json
{
  "action_name": "extract_data",
  "action_index": 0,
  "total_actions": 0,
  "execution_time": 15.2,
  "output_path": "",
  "record_count": 0,
  "tokens": {"prompt_tokens": 800, "completion_tokens": 400, "total_tokens": 1200},
  "mode": "",
  "model_vendor": "",
  "model_name": "",
  "kind": ""
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

## Console Output

Do not call `console.print()` from framework code to report progress. Fire an event instead, and the console handler formats it:

```python
fire_event(ActionCompleteEvent(
    action_name="my_action",
    execution_time=1.5,
))
```

## Performance Considerations

### Buffering

JSONFileHandler buffers events before writing:

```python
json_handler = JSONFileHandler(
    file_path=log_file,
    buffer_size=10,  # Write every 10 events
)
```

`LoggerFactory` sets `buffer_size=5` for `events.json` and `buffer_size=1` for `errors.json`.

### Handler Acceptance

Handlers filter events early to avoid unnecessary processing:

```python
def accepts(self, event: BaseEvent) -> bool:
    # Quick check before handle() is called
    level_order = EventLevel.ordered()
    return level_order.index(event.level) >= level_order.index(self.min_level)
```

### Context Copying

EventManager copies context to avoid mutation issues:

```python
# invocation_id and correlation_id are set on the event's meta;
# every other context key, such as workflow_name, goes into meta.extra
event.meta.invocation_id = context["invocation_id"]
event.meta.extra["workflow_name"] = context["workflow_name"]
```

## See Also

- [API Reference](../../api/logging.md) - Detailed API documentation
