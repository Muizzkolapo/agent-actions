# Logging API Reference

Complete API reference for agent-actions' event-based logging system.

## Public API

### fire_event()

Emit an event to all registered handlers.

```python
from agent_actions.logging import fire_event
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(
    message="Starting workflow",
    workflow_name="my_workflow",
    agent_count=5,
))
```

**Parameters:**
- `event` (BaseEvent): Event instance to fire

**Returns:** None

**Context Enrichment:**
Events are automatically enriched with correlation context from the EventManager before being dispatched to handlers.

---

### get_manager()

Get the EventManager singleton instance.

```python
from agent_actions.logging import get_manager

manager = get_manager()
manager.set_context(workflow_name="my_workflow")
```

**Returns:** EventManager instance

---

### LoggerFactory

Factory class for initializing and managing the logging system.

#### LoggerFactory.initialize()

Initialize the unified logging system with event handlers.

```python
from agent_actions.logging import LoggerFactory

manager = LoggerFactory.initialize(
    output_dir="/path/to/workflow/agent_io",
    workflow_name="my_workflow",
    invocation_id="run_abc123",
    verbose=True,
    force=True,
)
```

**Parameters:**
- `config` (Optional[LoggingConfig]): Logging configuration. If None, uses defaults from environment.
- `output_dir` (Optional[str | Path]): Directory for run_results.json and event logs. Defaults to None.
- `workflow_name` (str): Name of the workflow being executed. Defaults to "".
- `invocation_id` (Optional[str]): Unique ID for this invocation. Auto-generated if not provided.
- `verbose` (bool): Show DEBUG level events on console. Defaults to False.
- `quiet` (bool): Only show WARN and ERROR events on console. Defaults to False.
- `force` (bool): Reinitialize even if already initialized. Defaults to False.

**Returns:** EventManager instance

**Side Effects:**
- Creates and registers ConsoleEventHandler
- Creates and registers JSONFileHandler (if output_dir provided)
- Creates and registers RunResultsCollector (if output_dir provided)
- Sets up LoggingBridgeHandler to convert Python logging to events
- Sets correlation context (invocation_id, workflow_name)

**Example:**
```python
# Typical CLI initialization
manager = LoggerFactory.initialize(
    output_dir=agent_folder,
    workflow_name="product_analysis",
    invocation_id="run_xyz789",
    verbose=args.verbose,
    force=True,
)

# Events are now routed to:
# - Console (Rich-formatted output)
# - agent_folder/target/events.json
# - agent_folder/target/run_results.json
```

#### LoggerFactory.get_logger()

Get a Python logger that routes through the event system.

```python
logger = LoggerFactory.get_logger("my_module")
logger.info("Processing item")  # Converted to LogEvent
```

**Parameters:**
- `name` (str): Logger name. Auto-prefixed with 'agent_actions.' if not already.

**Returns:** logging.Logger instance

**Note:** All logging calls are converted to LogEvent instances and routed through EventManager.

#### LoggerFactory.set_context()

Set shared context values for all events.

```python
LoggerFactory.set_context(
    workflow_name="my_workflow",
    correlation_id="abc123",
    agent_name="extract_data",
)
```

**Parameters:**
- `**kwargs`: Arbitrary context key-value pairs

**Returns:** None

**Note:** Context is automatically attached to all events emitted after this call.

#### LoggerFactory.flush()

Flush all event handlers (write buffered data).

```python
try:
    run_workflow()
finally:
    LoggerFactory.flush()  # Ensure all events are written
```

**Returns:** None

**Important:** Always call before process exit to ensure buffered events are written.

#### LoggerFactory.get_event_manager()

Get the current EventManager instance.

```python
manager = LoggerFactory.get_event_manager()
```

**Returns:** Optional[EventManager]

**Returns None if:** LoggerFactory hasn't been initialized yet.

#### LoggerFactory.get_run_results_collector()

Get the RunResultsCollector instance.

```python
collector = LoggerFactory.get_run_results_collector()
```

**Returns:** Optional[RunResultsCollector]

**Returns None if:** LoggerFactory hasn't been initialized or no output_dir was provided.

#### LoggerFactory.reset()

Reset the factory state (for testing).

```python
LoggerFactory.reset()
```

**Returns:** None

**Warning:** This clears all handlers and state. Only use in tests.

---

## EventManager

Central event dispatcher that routes events to handlers.

### EventManager.get()

Get the EventManager singleton instance.

```python
from agent_actions.logging.core import EventManager

manager = EventManager.get()
```

**Returns:** EventManager instance

---

### EventManager.initialize()

Mark the EventManager as initialized.

```python
manager.initialize()
```

**Returns:** None

**Note:** This is called automatically by LoggerFactory.initialize().

---

### EventManager.register()

Register an event handler.

```python
from agent_actions.logging.core import ConsoleEventHandler

handler = ConsoleEventHandler()
manager.register(handler)
```

**Parameters:**
- `handler` (EventHandler): Handler instance with `accepts()` and `handle()` methods

**Returns:** None

---

### EventManager.register_function()

Register a simple function as a handler.

```python
def my_handler(event):
    print(f"Event: {event.message}")

manager.register_function(my_handler)
```

**Parameters:**
- `func` (Callable[[BaseEvent], None]): Function that takes an event

**Returns:** None

**Note:** Function will receive all events (no filtering).

---

### EventManager.fire()

Fire an event to all registered handlers.

```python
from agent_actions.logging.events import WorkflowStartEvent

event = WorkflowStartEvent(
    message="Starting",
    workflow_name="my_workflow",
)
manager.fire(event)
```

**Parameters:**
- `event` (BaseEvent): Event to fire

**Returns:** None

**Note:** Event is enriched with context before being dispatched.

---

### EventManager.set_context()

Set correlation context for all events.

```python
manager.set_context(
    workflow_name="my_workflow",
    correlation_id="abc123",
)
```

**Parameters:**
- `**kwargs`: Context key-value pairs

**Returns:** None

---

### EventManager.context()

Context manager for temporary context override.

```python
with manager.context(workflow_name="upstream"):
    fire_event(WorkflowStartEvent(message="Starting upstream"))
    # Event has workflow_name="upstream"

# Context restored to previous value
```

**Parameters:**
- `**kwargs`: Temporary context values

**Returns:** Context manager

**Yields:** None

---

### EventManager.flush()

Flush all registered handlers.

```python
manager.flush()
```

**Returns:** None

---

### EventManager.reset()

Reset EventManager state (for testing).

```python
EventManager.reset()
```

**Returns:** None

**Warning:** Clears all handlers and context. Only use in tests.

---

## Event Classes

All event classes inherit from `BaseEvent` and are dataclasses.

### BaseEvent

Base class for all events.

```python
from agent_actions.logging.events.base import BaseEvent, EventCategory

@dataclass
class MyEvent(BaseEvent):
    category: EventCategory = EventCategory.SYSTEM
    event_type: str = "my_event"

    # Custom fields
    custom_field: str = ""

    def __post_init__(self):
        super().__post_init__()
        self.data["custom_field"] = self.custom_field
```

**Attributes:**
- `event_id` (str): Unique event identifier (auto-generated)
- `timestamp` (datetime): Event timestamp (auto-generated)
- `category` (EventCategory): Event category
- `event_type` (str): Specific event type
- `message` (str): Human-readable message
- `data` (Dict[str, Any]): Structured event data
- `meta` (EventMetadata): Metadata (invocation_id, workflow_name, etc.)

---

### Workflow Events

#### WorkflowStartEvent

Emitted when a workflow starts executing.

```python
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(
    message="Starting workflow",
    workflow_name="my_workflow",
    agent_count=5,
    execution_mode="parallel",
))
```

**Fields:**
- `workflow_name` (str): Workflow name
- `agent_count` (int): Number of agents in workflow
- `execution_mode` (str): "sequential" or "parallel"

---

#### WorkflowCompleteEvent

Emitted when a workflow completes successfully.

```python
from agent_actions.logging.events import WorkflowCompleteEvent

fire_event(WorkflowCompleteEvent(
    message="Workflow completed",
    workflow_name="my_workflow",
    execution_time=119.5,
    agents_completed=5,
    total_tokens={"prompt": 10000, "completion": 2500},
))
```

**Fields:**
- `workflow_name` (str): Workflow name
- `execution_time` (float): Total execution time in seconds
- `agents_completed` (int): Number of agents completed
- `total_tokens` (Dict[str, int]): Aggregated token usage

---

#### WorkflowErrorEvent

Emitted when a workflow fails.

```python
from agent_actions.logging.events import WorkflowErrorEvent

fire_event(WorkflowErrorEvent(
    message="Workflow failed",
    workflow_name="my_workflow",
    error_message="Dependency cycle detected",
    error_type="CyclicDependencyError",
))
```

**Fields:**
- `workflow_name` (str): Workflow name
- `error_message` (str): Error description
- `error_type` (str): Exception class name

---

### Agent Events

#### AgentStartEvent

Emitted when an agent starts processing.

```python
from agent_actions.logging.events import AgentStartEvent

fire_event(AgentStartEvent(
    message="Starting agent",
    agent_name="extract_data",
    agent_index=1,
    total_agents=5,
    model_vendor="openai",
    model_name="gpt-4o-mini",
))
```

**Fields:**
- `agent_name` (str): Agent name
- `agent_index` (int): Agent position in workflow (1-based)
- `total_agents` (int): Total number of agents
- `model_vendor` (str): LLM provider
- `model_name` (str): Model identifier

---

#### AgentCompleteEvent

Emitted when an agent completes successfully.

```python
from agent_actions.logging.events import AgentCompleteEvent

fire_event(AgentCompleteEvent(
    message="Agent completed",
    agent_name="extract_data",
    execution_time=15.2,
    tokens={"prompt": 800, "completion": 400},
    record_count=100,
))
```

**Fields:**
- `agent_name` (str): Agent name
- `execution_time` (float): Execution time in seconds
- `tokens` (Dict[str, int]): Token usage
- `record_count` (int): Number of records processed

---

#### AgentSkippedEvent

Emitted when an agent is skipped (guard condition).

```python
from agent_actions.logging.events import AgentSkippedEvent

fire_event(AgentSkippedEvent(
    message="Agent skipped",
    agent_name="optional_enrichment",
    skip_reason="Guard condition failed: confidence < 0.8",
    skip_strategy="guard",
))
```

**Fields:**
- `agent_name` (str): Agent name
- `skip_reason` (str): Why agent was skipped
- `skip_strategy` (str): Skip mechanism ("guard", "cache", etc.)

---

#### AgentFailedEvent

Emitted when an agent fails.

```python
from agent_actions.logging.events import AgentFailedEvent

fire_event(AgentFailedEvent(
    message="Agent failed",
    agent_name="extract_data",
    error_message="API rate limit exceeded",
    error_type="RateLimitError",
))
```

**Fields:**
- `agent_name` (str): Agent name
- `error_message` (str): Error description
- `error_type` (str): Exception class name

---

### Batch Events

#### BatchSubmittedEvent

Emitted when a batch job is submitted.

```python
from agent_actions.logging.events import BatchSubmittedEvent

fire_event(BatchSubmittedEvent(
    message="Batch submitted",
    agent_name="extract_data",
    batch_id="batch_abc123",
    record_count=1000,
    model_vendor="openai",
))
```

**Fields:**
- `agent_name` (str): Agent name
- `batch_id` (str): Batch job ID
- `record_count` (int): Number of records in batch
- `model_vendor` (str): LLM provider

---

#### BatchCompleteEvent

Emitted when a batch job completes.

```python
from agent_actions.logging.events import BatchCompleteEvent

fire_event(BatchCompleteEvent(
    message="Batch completed",
    agent_name="extract_data",
    batch_id="batch_abc123",
    execution_time=3600.0,
    tokens={"prompt": 50000, "completion": 25000},
))
```

**Fields:**
- `agent_name` (str): Agent name
- `batch_id` (str): Batch job ID
- `execution_time` (float): Total time in seconds
- `tokens` (Dict[str, int]): Token usage

---

#### BatchErrorEvent

Emitted when a batch job fails.

```python
from agent_actions.logging.events import BatchErrorEvent

fire_event(BatchErrorEvent(
    message="Batch failed",
    agent_name="extract_data",
    batch_id="batch_abc123",
    error_message="Batch expired",
    error_type="BatchExpiredError",
))
```

**Fields:**
- `agent_name` (str): Agent name
- `batch_id` (str): Batch job ID
- `error_message` (str): Error description
- `error_type` (str): Exception class name

---

### Validation Events

#### ValidationStartEvent

Emitted when validation starts.

```python
from agent_actions.logging.events import ValidationStartEvent

fire_event(ValidationStartEvent(
    message="Starting validation",
    target="extract_data_schema",
))
```

**Fields:**
- `target` (str): What is being validated

---

#### ValidationPassEvent

Emitted when validation passes.

```python
from agent_actions.logging.events import ValidationPassEvent

fire_event(ValidationPassEvent(
    message="Validation passed",
    target="extract_data_schema",
))
```

**Fields:**
- `target` (str): What was validated

---

#### ValidationFailEvent

Emitted when validation fails.

```python
from agent_actions.logging.events import ValidationFailEvent

fire_event(ValidationFailEvent(
    message="Validation failed",
    target="extract_data_schema",
    errors=["Missing required field 'title'", "Invalid type for 'price'"],
))
```

**Fields:**
- `target` (str): What was validated
- `errors` (List[str]): Validation error messages

---

#### ValidationWarningEvent

Emitted for validation warnings.

```python
from agent_actions.logging.events import ValidationWarningEvent

fire_event(ValidationWarningEvent(
    message="Validation warning",
    target="extract_data_schema",
    warnings=["Optional field 'description' is missing"],
))
```

**Fields:**
- `target` (str): What was validated
- `warnings` (List[str]): Warning messages

---

## Event Handlers

### EventHandler (Base Class)

Base class for all event handlers.

```python
from agent_actions.logging.core.handlers import EventHandler

class MyHandler(EventHandler):
    def accepts(self, event: BaseEvent) -> bool:
        """Return True if this handler processes the event."""
        return event.category == "workflow"

    def handle(self, event: BaseEvent) -> None:
        """Process the event."""
        print(f"Event: {event.message}")

    def flush(self) -> None:
        """Flush any buffered data."""
        pass
```

**Methods:**
- `accepts(event)` → bool: Return True if handler processes this event
- `handle(event)` → None: Process the event
- `flush()` → None: Flush buffered data

---

### ConsoleEventHandler

Outputs events to the console using Rich formatting.

```python
from agent_actions.logging.core import ConsoleEventHandler, EventLevel

handler = ConsoleEventHandler(
    min_level=EventLevel.INFO,
    show_timestamp=True,
    categories={"workflow", "agent", "batch"},
)
```

**Parameters:**
- `min_level` (EventLevel): Minimum event level to display
- `show_timestamp` (bool): Include timestamp in output
- `formatter` (Optional[Callable]): Custom formatter function
- `categories` (Optional[Set[str]]): Event categories to display (None = all)

---

### JSONFileHandler

Writes events to a JSON file in NDJSON format.

```python
from agent_actions.logging.core import JSONFileHandler, EventLevel
from pathlib import Path

handler = JSONFileHandler(
    file_path=Path("logs/events.json"),
    min_level=EventLevel.DEBUG,
    buffer_size=10,
)
```

**Parameters:**
- `file_path` (Path): Output file path
- `min_level` (EventLevel): Minimum event level to log
- `buffer_size` (int): Number of events to buffer before writing

**Output Format:** NDJSON (one JSON object per line)

---

### RunResultsCollector

Collects workflow execution results into run_results.json.

```python
from agent_actions.logging.events.handlers import RunResultsCollector

collector = RunResultsCollector(
    output_dir="/path/to/agent_io",
    workflow_name="my_workflow",
)
```

**Parameters:**
- `output_dir` (Optional[str | Path]): Directory to write run_results.json
- `workflow_name` (str): Name of workflow being executed

**Output:** `{output_dir}/target/run_results.json`

**Methods:**
- `set_output_dir(output_dir)`: Set output directory after initialization
- `accepts(event)`: Returns True for workflow/agent category events
- `handle(event)`: Process event and update internal state
- `flush()`: Write run_results.json to disk

---

## Configuration

### LoggingConfig

Configuration for the logging system.

```python
from agent_actions.logging.config import LoggingConfig, FileHandlerConfig

config = LoggingConfig(
    default_level="INFO",
    file_handler=FileHandlerConfig(
        enabled=True,
        path="logs/events.json",
    ),
)

LoggerFactory.initialize(config=config)
```

**Fields:**
- `default_level` (str): Default log level ("DEBUG", "INFO", "WARN", "ERROR")
- `file_handler` (FileHandlerConfig): File handler configuration

#### FileHandlerConfig

```python
from agent_actions.logging.config import FileHandlerConfig

file_config = FileHandlerConfig(
    enabled=True,
    path="logs/events.json",
)
```

**Fields:**
- `enabled` (bool): Enable file logging
- `path` (str): Log file path (relative to project root)

---

## Constants

### EventLevel

Event severity levels.

```python
from agent_actions.logging.core import EventLevel

EventLevel.DEBUG    # Detailed diagnostic information
EventLevel.INFO     # General informational messages
EventLevel.WARN     # Warning messages
EventLevel.ERROR    # Error messages
```

---

### EventCategory

Event categories for filtering.

```python
from agent_actions.logging.events.base import EventCategory

EventCategory.WORKFLOW     # Workflow lifecycle events
EventCategory.AGENT        # Agent execution events
EventCategory.BATCH        # Batch processing events
EventCategory.VALIDATION   # Validation events
EventCategory.PROGRESS     # Progress updates
EventCategory.SYSTEM       # System-level events
```

---

## Examples

### Basic Workflow Logging

```python
from agent_actions.logging import LoggerFactory, fire_event
from agent_actions.logging.events import (
    WorkflowStartEvent,
    AgentStartEvent,
    AgentCompleteEvent,
    WorkflowCompleteEvent,
)

# Initialize
LoggerFactory.initialize(
    output_dir="my_workflow/agent_io",
    workflow_name="my_workflow",
)

# Workflow start
fire_event(WorkflowStartEvent(
    message="Starting workflow",
    workflow_name="my_workflow",
    agent_count=3,
))

# Agent 1
fire_event(AgentStartEvent(
    message="Starting agent",
    agent_name="extract",
    agent_index=1,
))
# ... do work ...
fire_event(AgentCompleteEvent(
    message="Agent completed",
    agent_name="extract",
    execution_time=5.2,
))

# Workflow complete
fire_event(WorkflowCompleteEvent(
    message="Workflow completed",
    workflow_name="my_workflow",
    execution_time=15.6,
))

# Flush
LoggerFactory.flush()
```

### Custom Event Handler

```python
from agent_actions.logging import get_manager
from agent_actions.logging.core.handlers import EventHandler
from agent_actions.logging.events.base import BaseEvent

class MetricsHandler(EventHandler):
    def __init__(self):
        self.metrics = []

    def accepts(self, event: BaseEvent) -> bool:
        return event.category in ("workflow", "agent")

    def handle(self, event: BaseEvent) -> None:
        if event.event_type == "agent_complete":
            self.metrics.append({
                "agent": event.data.get("agent_name"),
                "duration": event.data.get("execution_time"),
                "tokens": event.data.get("tokens", {}),
            })

    def flush(self) -> None:
        import json
        with open("metrics.json", "w") as f:
            json.dump(self.metrics, f, indent=2)

# Register
handler = MetricsHandler()
manager = get_manager()
manager.register(handler)
```

### Context Scoping

```python
from agent_actions.logging import get_manager, fire_event
from agent_actions.logging.events import AgentStartEvent

manager = get_manager()

# Set global context
manager.set_context(workflow_name="main")

# All events inherit workflow_name="main"
fire_event(AgentStartEvent(message="Agent 1", agent_name="extract"))

# Override for nested context
with manager.context(workflow_name="upstream"):
    fire_event(AgentStartEvent(message="Upstream agent", agent_name="fetch"))
    # Event has workflow_name="upstream"

# Back to workflow_name="main"
fire_event(AgentStartEvent(message="Agent 2", agent_name="transform"))
```

---

## See Also

- [Logging Architecture](../architecture/logging.md) - System design and flow
- [Event Types](../../events/types.md) - All available event types
- [Handler Development Guide](../../guides/handlers.md) - Creating custom handlers
