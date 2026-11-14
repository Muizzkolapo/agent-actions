# Logging Architecture

agent-actions uses an event-based logging architecture. It gives CLI output that is easy for users to read, and detailed structured logs for debugging and analytics.

## Overview

The logging system has two primary goals:

1. **User-facing output** - Clean, formatted progress messages while the workflow runs
2. **Structured logs** - A complete execution trace for debugging, analytics and integration

All logging goes through a central EventManager. The EventManager sends events to the registered handlers.

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

The EventManager is a singleton (one instance only). It does these functions:
- Receives all events from the application
- Adds correlation context to events (workflow_name, correlation_id and other keys)
- Routes events to the registered handlers
- Manages the lifecycle of the handlers

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

**Location:** `agent_actions/logging/events/` holds one module for each category of events. The `types.py` file in that directory holds the category constants. The base class, `BaseEvent`, is in `agent_actions/logging/core/events.py`.

Events are dataclasses. Each event represents a specific occurrence in the system. The name of the event class is the `event_type` that Agent Actions writes to `events.json`:

**Event Categories:**
- `workflow` - Events for the lifecycle of the workflow
- `action` - Events for action execution
- `batch` - Batch job operations
- `llm` - LLM requests and responses
- `validation` - Validation results
- `cache`, `template`, `data`, `guard`, `recovery` - Events for the cache, template rendering, data loading, guard evaluation and retries
- `configuration`, `initialization`, `plugin` - Events for configuration loading, CLI start-up and tool discovery
- `data_processing`, `file_io`, `schema`, `transformation` - Events for record processing, files, schemas and transformations

An event that sets no category has the category `system`.

**Common Events:**
- `WorkflowStartEvent` - The workflow starts
- `WorkflowCompleteEvent` - The workflow completes
- `WorkflowFailedEvent` - The workflow fails
- `ActionStartEvent` - The action starts to process
- `ActionCompleteEvent` - The action completes successfully
- `ActionSkipEvent` - The action was skipped (guard condition)
- `ActionFailedEvent` - The action fails with an error
- `BatchSubmittedEvent` - The batch job was submitted
- `BatchCompleteEvent` - The batch job completes
- `ValidationStartEvent` - Validation starts
- `ValidationCompleteEvent` - Validation passes
- `ValidationErrorEvent` - Validation fails

### Handlers

Handlers receive events and do work on them (for example, show output on the console or write to a file).

#### ConsoleEventHandler

**Location:** `agent_actions/logging/core/handlers/console.py`

Formats events for the CLI output that users see. It uses Rich.

**Features:**
- Output with a color for each event type
- Shows the timestamp
- Filters by category (workflow, action and batch events by default). Warnings and errors show for all categories.
- Verbose mode shows all events
- Drops events marked diagnostic, unless the run is verbose

#### ProgressRenderer

**Location:** `agent_actions/logging/core/handlers/progress.py`

The console handler that a run installs. It reads the workflow, step and action
events. It shows them as one grouped progress stream, with one line for each action.
Each action line is under the dependency step of that action. If it does not recognise an event, the
formatting of `ConsoleEventHandler` applies. Thus warnings and errors from all
modules do not change.

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

An action reports one time, when it completes. With `--verbose`, each action also reports
when it starts. The record count includes the records that the guard of the action skipped. Agent Actions
keeps these records as tombstones. `— N skipped by guard` gives the number of these records. The line
does not show this text when there are no skipped records:

```
  ✓ repaired  4 records in 0.2s (agac-provider/mock) — 1 skipped by guard
```

Some actions ship records with a failing [expectations](../validation/expectations.md) verdict
(`on_exhausted: return_last`, `repair: none`). The line of such an action turns to `⚠` (`WARN` without color). The line also gives
the number of these records. The workflow line counts every such record that the actions of the workflow hold. It reads the count from the
store. Thus, if a batch workflow completes over several runs, the count includes the records that the earlier runs
collected. The workflow line also turns to `⚠`, unless an action failed. If an action failed, the workflow line keeps `✗`. The exit code does not change. To gate CI on verdicts, use `agac expect report --fail-under`.

```
  ⚠ observed  4 records in 0.1s (agac-provider/mock) — 4 failed their checks
  ⚠ repaired  4 records in 0.1s (agac-provider/mock) — 1 skipped by guard, 3 failed their checks
  ✓ warned  4 records in 0.1s (agac-provider/mock)

⚠ 0.1s — 3 completed, 7 records failed their checks
```

The duration of a batch action has the mark `(batch)`. Thus the queue time at the provider
does not look like local work.

#### JSONFileHandler

**Location:** `agent_actions/logging/core/handlers/json_file.py`

Writes events to a JSON file in NDJSON format (one JSON object on each line).

**Features:**
- Buffered writes (you can configure the buffer size)
- Creates parent directories automatically
- NDJSON format, which is easy to stream and parse
- The full event payload, with metadata

**Output Location:** `{workflow}/agent_io/logs/events.json` holds all levels. A second handler writes `{workflow}/agent_io/logs/errors.json`, which holds only ERROR events.

**Example Entry** (one line in the file, shown here with indents so that you can read it):
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

Collects data about the workflow run and writes a `run_results.json` artifact.

**Features:**
- Tracks the execution status, the timing and the token usage of each action
- Adds the token counts into totals
- Records the output folder of each action
- Records error messages and skip reasons

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

This call does these steps:
1. Creates the EventManager singleton.
2. Registers ProgressRenderer (the console handler for a run).
3. Registers JSONFileHandler (writes all levels to `{output_dir}/logs/events.json`).
4. Registers a second JSONFileHandler (writes ERROR events to `{output_dir}/logs/errors.json`).
5. Registers RunResultsCollector (writes `{output_dir}/logs/run_results.json`).
6. Configures LoggingBridgeHandler to convert `logger.*` calls to events.

### 2. Event Emission

Code can emit events in two ways:

**Direct Events:**
```python
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    action_count=5,
))
```

**Python Logging (converted to events automatically):**
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Processing item 123")  # Becomes LogEvent
logger.error("Failed to process")   # Becomes LogEvent with ERROR level
```

### 3. Event Enrichment

EventManager automatically adds correlation context to events:

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

EventManager routes events to handlers. The acceptance criteria of each handler decide which events it gets:

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

Handlers process events and make output:
- **ConsoleHandler** → Terminal output, formatted with Rich
- **JSONFileHandler** → Adds to the end of `events.json`
- **RunResultsCollector** → Collects data, and writes `run_results.json` on flush

## Context Propagation

`manager.context()` puts context values over the current values for the code inside the block. It does this for each thread and each coroutine separately:

```python
with manager.context(workflow_name="upstream", correlation_id="abc123"):
    # All events in this scope inherit the context
    run_upstream()

# Context automatically restores after block
```

Thus each event goes to the correct workflow or action.

Each action runs inside `manager.context(action_name=..., action_index=...)`. Thus every event
that the action fires, also from its worker threads, names the action in `meta`. The actions of one step run at the same time.
That is why Agent Actions never sets the action with `set_context()`. All the actions share that value.

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

You can control the verbosity of the console:

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

The file handler attaches only when a workflow run passes `output_dir` to
`LoggerFactory.initialize()`. The `agac run`, `agac retry` and `agac batch` commands do this when they know the
output directory of the run:

```python
LoggerFactory.initialize(output_dir=agent_folder, workflow_name=..., invocation_id=run_id)
```

The file handler writes `{output_dir}/logs/events.json` (all levels) and
`{output_dir}/logs/errors.json` (ERROR level only). A command that does not
run a workflow never supplies `output_dir`. Examples are `agac inspect`, `validate-udfs` and other read-only
paths. Thus such a command registers no file handler and
writes nothing to disk.

## Best Practices

### 1. Use Typed Events

Do not use BaseEvent directly. Create specific event classes:

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

Event messages should be easy for a person to read, and should tell the reader what to do:

```python
# Good
message="Action extract_data completed in 15.2s"

# Bad
message="done"
```

### 3. Structured Data

Put data that a machine reads in the `data` dict:

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

Use context managers for nested execution contexts:

```python
with manager.context(workflow_name="upstream"):
    # All events here get workflow_name="upstream"
    execute_upstream()

# Context automatically restores
```

### 5. Flush Before Exit

Always flush the handlers before the program exits:

```python
try:
    run_workflow()
finally:
    LoggerFactory.flush()  # Ensure all buffered events are written
```

## Console Output

Do not call `console.print()` from framework code to report progress. Fire an event. The console handler formats the event:

```python
fire_event(ActionCompleteEvent(
    action_name="my_action",
    execution_time=1.5,
))
```

## Performance Considerations

### Buffering

JSONFileHandler buffers events before it writes them:

```python
json_handler = JSONFileHandler(
    file_path=log_file,
    buffer_size=10,  # Write every 10 events
)
```

`LoggerFactory` sets `buffer_size=5` for `events.json` and `buffer_size=1` for `errors.json`.

### Handler Acceptance

Handlers filter events early. This prevents unnecessary processing:

```python
def accepts(self, event: BaseEvent) -> bool:
    # Quick check before handle() is called
    level_order = EventLevel.ordered()
    return level_order.index(event.level) >= level_order.index(self.min_level)
```

### Context Copying

EventManager copies the context. This prevents problems from mutation:

```python
# invocation_id and correlation_id are set on the event's meta;
# every other context key, such as workflow_name, goes into meta.extra
event.meta.invocation_id = context["invocation_id"]
event.meta.extra["workflow_name"] = context["workflow_name"]
```

## See Also

- [API Reference](../../api/logging.md) - Detailed API documentation
