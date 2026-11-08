# Logging API Reference

Complete API reference for agent-actions' event-based logging system.

## Public API

### fire_event()

Emit an event to all registered handlers.

```python
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    action_count=5,
))
```

**Note:** Every event class sets its own `level`, `category`, `message` and `data` in `__post_init__`. A `message` you pass in is replaced.

**Parameters:**
- `event` (BaseEvent): Event instance to fire

**Returns:** None

**Context Enrichment:**
Before dispatch, the EventManager copies its context into the event's `meta`: `invocation_id` and `correlation_id` go to their own fields, and every other key goes to `meta.extra`.

---

### get_manager()

Get the EventManager singleton instance.

```python
from agent_actions.logging.core.manager import get_manager

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
from agent_actions.logging.factory import LoggerFactory

manager = LoggerFactory.initialize(
    output_dir="/path/to/workflow/agent_io",
    workflow_name="my_workflow",
    invocation_id="run_abc123",
    verbose=True,
    force=True,
    new_run=True,
)
```

**Parameters:**
- `config` (Optional[LoggingConfig]): Logging configuration. If None, keeps the configuration of an earlier call; if there was none, reads the `AGENT_ACTIONS_*` environment variables.
- `output_dir` (Optional[str | Path]): Directory whose `logs/` subdirectory receives `events.json`, `errors.json` and `run_results.json`. Defaults to None.
- `workflow_name` (str): Name of the workflow being executed. Defaults to "".
- `invocation_id` (Optional[str]): Unique ID for this invocation. An 8-character ID is generated if not provided.
- `verbose` (Optional[bool]): Show DEBUG level events, all categories, and diagnostic events on console. `None` (the default) keeps whatever a previous call configured, so a `force=True` re-init that omits it does not discard the CLI's flags.
- `quiet` (Optional[bool]): Only show WARN and ERROR events on console. `None` (the default) keeps whatever a previous call configured.
- `force` (bool): Reinitialize even if already initialized. Defaults to False.
- `new_run` (bool): Mark the start of a workflow run. The run logs in `output_dir/logs` rotate first, so `events.json` holds this run only. Other commands append to the current run's file. Defaults to False.

**Returns:** EventManager instance

**Side Effects:**
- Creates and registers ProgressRenderer (the run's console handler)
- Creates and registers two JSONFileHandler instances (if output_dir provided): `logs/events.json` at DEBUG and `logs/errors.json` at ERROR
- Creates and registers RunResultsCollector (it writes `logs/run_results.json` only if output_dir provided)
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
# - Console (stderr, Rich-formatted when Rich is available)
# - agent_folder/logs/events.json
# - agent_folder/logs/errors.json
# - agent_folder/logs/run_results.json
```

#### LoggerFactory.get_logger()

Get a Python logger that routes through the event system.

```python
logger = LoggerFactory.get_logger("my_module")
logger.info("Processing item")  # Converted to LogEvent
```

**Parameters:**
- `name` (str): Logger name. Auto-prefixed with 'agent_actions.' if not already.

**Returns:** logging.Logger instance. Initializes the factory first if it is not initialized.

**Note:** Every record logged under the `agent_actions` namespace is converted to a LogEvent and routed through EventManager.

#### LoggerFactory.set_context()

Set shared context values for all events.

```python
LoggerFactory.set_context(
    workflow_name="my_workflow",
    correlation_id="abc123",
)
```

**Parameters:**
- `**kwargs`: Arbitrary context key-value pairs

**Returns:** None

**Note:** Context is automatically attached to all events emitted after this call, whatever action fires them. Put a per-action or per-batch value in `EventManager.context()` or in the event's own fields instead.

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
from agent_actions.logging.core.manager import EventManager

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
from agent_actions.logging.core.handlers import ConsoleEventHandler

handler = ConsoleEventHandler()
manager.register(handler)
```

**Parameters:**
- `handler` (EventHandler): Handler instance with `accepts()`, `handle()` and `flush()` methods. The manager calls `close()` on reset if the handler has one.

**Returns:** None

---

### EventManager.unregister()

Remove a registered handler. Does nothing if the handler is not registered.

```python
manager.unregister(handler)
```

**Parameters:**
- `handler` (EventHandler): Handler instance to remove

**Returns:** None

---

### EventManager.fire()

Fire an event to all registered handlers.

```python
from agent_actions.logging.events import WorkflowStartEvent

event = WorkflowStartEvent(workflow_name="my_workflow", action_count=3)
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

The values are process-wide: every later event in the process carries them in `meta`, whatever action fires it. A per-action or per-batch value belongs in `context()` below, or in the event's own `data` (a batch id is in the batch events' `data.batch_id`).

---

### EventManager.context()

Context manager for temporary context override.

```python
with manager.context(workflow_name="upstream"):
    fire_event(WorkflowStartEvent(workflow_name="upstream", action_count=2))
    # event.meta.extra["workflow_name"] == "upstream"

# Context restored to previous value
```

The override is local to the current thread or coroutine, and calls can nest.

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
from dataclasses import dataclass

from agent_actions.logging.core.events import BaseEvent, EventLevel

@dataclass
class MyEvent(BaseEvent):
    custom_field: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = "system"
        self.message = f"My event: {self.custom_field}"
        self.data = {"custom_field": self.custom_field}
```

**Attributes:**
- `level` (EventLevel): Severity
- `category` (str): Event category; see [EventCategories](#eventcategories)
- `message` (str): Human-readable message
- `meta` (EventMeta): `timestamp`, `correlation_id`, `invocation_id`, `thread_id` and `extra` (the other context keys)
- `data` (Dict[str, Any]): Structured event data
- `diagnostic` (bool): Framework internals rather than something the user can act on. Kept by the file handlers, dropped by the console unless verbose
- `event_type` (str, read-only property): The event class name, such as `"ActionStartEvent"`

---

### Workflow Events

#### WorkflowStartEvent

Emitted when a workflow starts executing.

```python
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    action_count=5,
    execution_mode="async",
))
```

**Note:** The `message` field is generated from `workflow_name` and `action_count`.

**Fields:**
- `workflow_name` (str): Workflow name
- `action_count` (int): Number of actions in the workflow
- `execution_mode` (str): `"sequential"` or `"async"`. The workflow runner sets it; it defaults to `"sequential"`

---

#### WorkflowCompleteEvent

Emitted when a workflow completes successfully.

```python
from agent_actions.logging.events import WorkflowCompleteEvent

fire_event(WorkflowCompleteEvent(
    workflow_name="my_workflow",
    elapsed_time=119.5,
    actions_completed=5,
    actions_partial=0,
    actions_skipped=0,
    actions_failed=0,
    total_tokens=12500,
))
```

**Fields:**
- `workflow_name` (str): Workflow name
- `elapsed_time` (float): Total execution time in seconds
- `actions_completed` (int): Number of actions completed
- `actions_partial` (int): Number of actions that completed with failed records
- `actions_skipped` (int): Number of actions skipped
- `actions_failed` (int): Number of actions failed
- `total_tokens` (int): Total tokens used
- `records_failed_checks` (int): Records the workflow's actions hold that shipped with an expectations verdict whose `overall_pass` is false, read from the store as the run ends. A batch workflow finishing over several runs counts what the earlier runs collected. The workflow line turns `⚠` and says `N records failed their checks` when it is above zero

---

#### WorkflowFailedEvent

Emitted when a workflow fails.

```python
from agent_actions.logging.events import WorkflowFailedEvent

fire_event(WorkflowFailedEvent(
    workflow_name="my_workflow",
    error_message="Dependency cycle detected",
    error_type="CyclicDependencyError",
    elapsed_time=5.2,
    failed_action="extract_data",
))
```

**Fields:**
- `workflow_name` (str): Workflow name
- `error_message` (str): Error description
- `error_detail` (str): Further detail on the error
- `error_type` (str): Exception type name
- `elapsed_time` (float): Time elapsed before failure
- `failed_action` (str): Name of the action that failed

---

#### StepStartEvent

Emitted when a dependency level begins. Fires even when nothing in it is pending.

```python
from agent_actions.logging.events import StepStartEvent

fire_event(StepStartEvent(
    step_index=1,
    total_steps=3,
    actions=["extract_a", "extract_b"],
    pending=["extract_b"],
))
```

**Fields:**
- `step_index` (int): Level position, 0-based (rendered 1-based)
- `total_steps` (int): Number of levels in the run
- `actions` (List[str]): Every action in the level
- `pending` (List[str]): The subset that will actually run

---

#### StepCompleteEvent

Emitted when a dependency level ends, whatever the outcome.

```python
from agent_actions.logging.events import StepCompleteEvent

fire_event(StepCompleteEvent(
    step_index=1,
    total_steps=3,
    elapsed_time=12.4,
    completed=2,
))
```

**Fields:**
- `step_index` / `total_steps` (int): As above
- `elapsed_time` (float): Wall time for the level
- `completed` / `partial` / `skipped` / `failed` / `unfinished` (int): Outcome tallies; they sum to the size of the level
- `batch_pending` (List[str]): Actions whose batch jobs are still outstanding; non-empty means the level paused rather than finished

---

### Action Events

#### ActionStartEvent

Emitted when an action starts processing.

```python
from agent_actions.logging.events import ActionStartEvent

fire_event(ActionStartEvent(
    action_name="extract_data",
    action_index=0,  # 0-based index
    total_actions=5,
    action_type="llm",
    input_path="/path/to/input.json",
    mode="online",
))
```

**Fields:**
- `action_name` (str): Action name
- `action_index` (int): Action position in workflow (0-based)
- `total_actions` (int): Total number of actions
- `action_type` (str): The action's kind (`"llm"`, `"tool"`, `"hitl"`)
- `input_path` (str): Path to input file
- `mode` (str): `"online"` or `"batch"`

---

#### ActionCompleteEvent

Emitted when an action completes successfully.

```python
from agent_actions.logging.events import ActionCompleteEvent

fire_event(ActionCompleteEvent(
    action_name="extract_data",
    action_index=0,
    total_actions=5,
    execution_time=15.2,
    output_path="/path/to/output.json",
    record_count=100,
    tokens={"prompt_tokens": 800, "completion_tokens": 400, "total_tokens": 1200},
    model_vendor="openai",
    model_name="gpt-4o",
    kind="llm",
))
```

**Fields:**
- `action_name` (str): Action name
- `action_index` (int): Action position in workflow (0-based)
- `total_actions` (int): Total number of actions
- `execution_time` (float): Execution time in seconds
- `output_path` (str): Path to output file
- `record_count` (int): Number of records this execution produced. A run that replaces rows already stored counts them again, so `agac run --rerun` and `agac retry` report what they answered. Records carried forward from an earlier run are not counted. The `✓ <action>  N records` completion line shows the same number.
- `guard_skipped` (int): Of `record_count`, the records the action's guard skipped this execution, kept as tombstones. The completion line ends `— N skipped by guard` when it is above zero.
- `checks_failed` (int): The records this execution shipped carrying an expectations verdict whose `overall_pass` is false (`on_exhausted: return_last`, `repair: none`). They are stored as successes; the completion line turns `⚠` and says `N failed their checks` when it is above zero.
- `tokens` (Dict[str, int]): Token usage breakdown
- `mode` (str): `"online"` or `"batch"`
- `model_vendor` / `model_name` (str): The model that ran the action; empty for a tool or HITL action
- `kind` (str): `"llm"`, `"tool"`, `"hitl"`, … — consumers use it to decide whether a model is meaningful

---

#### ActionSkipEvent

Emitted when an action is skipped, for example when its guard condition filters every record.

```python
from agent_actions.logging.events import ActionSkipEvent

fire_event(ActionSkipEvent(
    action_name="optional_enrichment",
    action_index=2,
    total_actions=5,
    skip_reason="guard condition not met",
))
```

**Fields:**
- `action_name` (str): Action name
- `action_index` (int): Action position in workflow (0-based)
- `total_actions` (int): Total number of actions
- `skip_reason` (str): Why action was skipped
- `mode` (str): `"online"` or `"batch"`

---

#### ActionFailedEvent

Emitted when an action fails.

```python
from agent_actions.logging.events import ActionFailedEvent

fire_event(ActionFailedEvent(
    action_name="extract_data",
    action_index=0,
    total_actions=5,
    error_message="API rate limit exceeded",
    error_type="RateLimitError",
    execution_time=2.5,
    suggestion="Try again after rate limit resets",
))
```

**Fields:**
- `action_name` (str): Action name
- `action_index` (int): Action position in workflow (0-based)
- `total_actions` (int): Total number of actions
- `error_message` (str): Error description
- `error_detail` (str): Further detail on the error
- `error_type` (str): Exception class name
- `execution_time` (float): Time elapsed before failure
- `suggestion` (str): Suggested fix or next step
- `mode` (str): `"online"` or `"batch"`

---

### Batch Events

#### BatchSubmittedEvent

Emitted when a batch job is submitted.

```python
from agent_actions.logging.events import BatchSubmittedEvent

fire_event(BatchSubmittedEvent(
    batch_id="batch_abc123",
    action_name="extract_data",
    request_count=1000,
    provider="openai",
))
```

**Fields:**
- `batch_id` (str): Batch job ID
- `action_name` (str): Action name
- `request_count` (int): Number of requests in batch
- `provider` (str): LLM provider

---

#### BatchCompleteEvent

Emitted when a batch job completes.

```python
from agent_actions.logging.events import BatchCompleteEvent

fire_event(BatchCompleteEvent(
    batch_id="batch_abc123",
    action_name="extract_data",
    total=1000,
    completed=995,
    failed=5,
    elapsed_time=3600.0,
    total_tokens=75000,
))
```

**Fields:**
- `batch_id` (str): Batch job ID
- `action_name` (str): Action name
- `total` (int): Total requests in batch
- `completed` (int): Successfully completed requests
- `failed` (int): Failed requests
- `elapsed_time` (float): Total time in seconds
- `total_tokens` (int): Total tokens used

---

#### BatchErrorEvent

Emitted when a batch job fails.

```python
from agent_actions.logging.events import BatchErrorEvent

fire_event(BatchErrorEvent(
    action_name="extract_data",
    error_message="Batch expired",
    error_type="BatchExpiredError",
))
```

**Fields:**
- `action_name` (str): Action name
- `error_message` (str): Error description
- `error_type` (str): Exception class name

---

### Validation Events

#### ValidationStartEvent

Emitted when validation starts.

```python
from agent_actions.logging.events import ValidationStartEvent

fire_event(ValidationStartEvent(
    target="extract_data_schema",
    validator="schema",
))
```

**Fields:**
- `target` (str): What is being validated
- `validator` (str): Name of the validator

---

#### ValidationCompleteEvent

Emitted when validation completes.

```python
from agent_actions.logging.events import ValidationCompleteEvent

fire_event(ValidationCompleteEvent(
    target="extract_data_schema",
    validator="schema",
    elapsed_time=0.02,
))
```

**Fields:**
- `target` (str): What was validated
- `validator` (str): Name of the validator
- `elapsed_time` (float): Validation time in seconds
- `warning_count` (int): Number of warnings found
- `error_count` (int): Number of errors found; the event's level is ERROR when this is not 0

---

#### ValidationErrorEvent

Emitted when validation finds an error.

```python
from agent_actions.logging.events import ValidationErrorEvent

fire_event(ValidationErrorEvent(
    target="extract_data_schema",
    field="title",
    error="Missing required field",
))
```

**Fields:**
- `target` (str): What was validated
- `field` (str): Which field failed
- `error` (str): Error description
- `value` (Any): The invalid value (optional)

---

#### ValidationWarningEvent

Emitted for validation warnings.

```python
from agent_actions.logging.events import ValidationWarningEvent

fire_event(ValidationWarningEvent(
    target="extract_data_schema",
    field="description",
    warning="Optional field is missing",
))
```

**Fields:**
- `target` (str): What was validated
- `field` (str): Which field triggered the warning
- `warning` (str): Warning message
- `value` (Any): The problematic value (optional)

---

## Event Handlers

### EventHandler (Base Class)

Base class for all event handlers.

`EventHandler` is a `Protocol` in `agent_actions.logging.core.protocols`. A handler is any object with these methods; it does not need to subclass it.

```python
from agent_actions.logging.core.events import BaseEvent

class MyHandler:
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
- `close()` → None: Release resources. The protocol lists it; the manager calls it on reset and on a forced re-initialize if the handler has it

---

### ProgressRenderer

The console handler a run installs. Subclasses `ConsoleEventHandler` and renders
workflow, step and action events as a grouped per-step progress stream; every
other event falls through to the formatting below.

```python
from agent_actions.logging.core.handlers import ProgressRenderer
```

Takes the same parameters as `ConsoleEventHandler`.

---

### ConsoleEventHandler

Writes events to the console (stderr), using Rich formatting when Rich is available.

```python
from agent_actions.logging.core.events import EventLevel
from agent_actions.logging.core.handlers import ConsoleEventHandler

handler = ConsoleEventHandler(
    min_level=EventLevel.INFO,
    show_timestamp=True,
    categories={"workflow", "action", "batch"},
)
```

**Parameters:**
- `min_level` (EventLevel): Minimum event level to display. Defaults to `EventLevel.INFO`
- `show_timestamp` (bool): Include timestamp in output. Defaults to True
- `formatter` (Optional[Callable]): Custom formatter function that takes an event and returns a string
- `console` (Optional[Any]): Rich console to write to. Defaults to a Rich console on stderr
- `categories` (Optional[Set[str]]): Event categories to display (None = all). WARN and ERROR events show whatever their category
- `show_diagnostics` (bool): Display events marked diagnostic. Defaults to False, which drops them at any level

---

### JSONFileHandler

Writes events to a JSON file in NDJSON format.

```python
from agent_actions.logging.core.events import EventLevel
from agent_actions.logging.core.handlers import JSONFileHandler
from pathlib import Path

handler = JSONFileHandler(
    file_path=Path("logs/events.json"),
    min_level=EventLevel.DEBUG,
    buffer_size=10,
)
```

**Parameters:**
- `file_path` (str | Path): Output file path. Parent directories are created
- `min_level` (EventLevel): Minimum event level to log. Defaults to `EventLevel.DEBUG`
- `buffer_size` (int): Number of events to buffer before writing. Defaults to 10
- `max_debug_bytes` (Optional[int]): Past this many bytes in the file, DEBUG events are no longer written. Defaults to None (no cap)
- `include_all_fields` (bool): True writes each event's full dictionary; False writes only `event_type`, `level`, `message` and `timestamp`. Defaults to True

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

**Output:** `{output_dir}/logs/run_results.json`

**Methods:**
- `accepts(event)`: Returns True for workflow and action category events, plus `RecordEmptyOutputEvent` and `ResultCollectionCompleteEvent`
- `handle(event)`: Process event and update internal state
- `flush()`: Write run_results.json to disk

---

## Configuration

### LoggingConfig

Configuration for the logging system.

```python
from agent_actions.logging.config import LoggingConfig

config = LoggingConfig(default_level="INFO")

LoggerFactory.initialize(config=config)
```

**Fields:**
- `default_level` (str): Default log level ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"). `from_environment()` reads it from `AGENT_ACTIONS_LOG_LEVEL`, and `AGENT_ACTIONS_DEBUG=1` forces `"DEBUG"`
- `module_levels` (dict): Per-logger level overrides applied at init. Keys are
  Python logger names (e.g. `"httpx"`, `"my_module"`), values are level
  strings. Use this to re-enable a logger the framework clamps by default,
  or to silence one that's still too chatty.
- `file_handler` (FileHandlerSettings): `max_bytes` and `backup_count` size and
  rotate the run log — see [File Handler](#filehandlersettings) below

#### Third-party logger suppression

To keep the CLI focused on framework output, `LoggerFactory.initialize()`
clamps a curated set of SDK / HTTP loggers to `WARNING` on every init:

```
httpx, httpcore, urllib3, openai, anthropic, ollama, groq,
cohere, google_genai, googleapiclient, sentence_transformers,
transformers, pypdf
```

To opt back in to verbose output from one of these — or to silence a logger
not in the curated list — pass `module_levels` when constructing the config:

```python
from agent_actions.logging.config import LoggingConfig
from agent_actions.logging.factory import LoggerFactory

config = LoggingConfig(
    default_level="INFO",
    module_levels={
        "httpx": "INFO",         # see HTTP request lines from httpx again
        "transformers": "ERROR", # silence model-loading chatter further
    },
)
LoggerFactory.initialize(config=config)
```

Overrides on `agent_actions` and any of its children are refused with a
stderr warning — the framework root must stay at DEBUG so every event reaches
`events.json`. Use `default_level` to set the CLI-visible level instead.

From the CLI, set the same thing under `logging.module_levels` in
`agent_actions.yml`: the CLI builds its config with
`LoggingConfig.from_environment(LoggingConfig.from_project_config(project_config))`
at boot, so the project block is the base and a set `AGENT_ACTIONS_*` variable
overrides only its own key. `module_levels` has no environment form. See
[Configuration](../reference/configuration#project-configuration).

#### FileHandlerSettings

`LoggingConfig.file_handler` is a `FileHandlerSettings` with two fields, and
`LoggerFactory` reads both: `max_bytes` (`logging.file.max_bytes` / `AGENT_ACTIONS_LOG_MAX_BYTES`)
caps the DEBUG rows written per run file, and `backup_count`
(`logging.file.backup_count` / `AGENT_ACTIONS_LOG_RETAIN_RUNS`) is how many
earlier runs are kept. Whether a run-log file handler is registered, and where
it writes, is decided entirely by the `output_dir` passed to
`LoggerFactory.initialize()`; the file is always `events.json` at DEBUG. Any
other `logging.file.*` project key, and the `AGENT_ACTIONS_NO_LOG_FILE`,
`AGENT_ACTIONS_LOG_FILE`, `AGENT_ACTIONS_LOG_DIR`, `AGENT_ACTIONS_FILE_LOG_LEVEL`
and `AGENT_ACTIONS_LOG_FORMAT` env vars, configure nothing: the CLI reports each
one that is set on stderr at boot and ignores it (see the architecture doc's File Handler section).

---

## Constants

### EventLevel

Event severity levels.

```python
from agent_actions.logging.core.events import EventLevel

EventLevel.DEBUG    # Detailed diagnostic information
EventLevel.INFO     # General informational messages
EventLevel.WARN     # Warning messages
EventLevel.ERROR    # Error messages
```

---

### EventCategories

Event category strings for filtering. `event.category` holds one of these values.

```python
from agent_actions.logging.events.types import EventCategories

EventCategories.WORKFLOW         # "workflow"        Workflow lifecycle events
EventCategories.ACTION           # "action"          Action execution events
EventCategories.BATCH            # "batch"           Batch processing events
EventCategories.LLM              # "llm"             LLM interaction events
EventCategories.VALIDATION       # "validation"      Validation events
EventCategories.CACHE            # "cache"           Cache events
EventCategories.TEMPLATE         # "template"        Template rendering events
EventCategories.DATA             # "data"            Data loading and parsing events
EventCategories.GUARD            # "guard"           Guard evaluation events
EventCategories.RECOVERY         # "recovery"        Recovery and retry events
EventCategories.CONFIGURATION    # "configuration"   Configuration loading events
EventCategories.INITIALIZATION   # "initialization"  Initialization events
EventCategories.PLUGIN           # "plugin"          Plugin and UDF discovery events
EventCategories.DATA_PROCESSING  # "data_processing" Data processing events
EventCategories.FILE_IO          # "file_io"         File I/O events
EventCategories.SCHEMA           # "schema"          Schema operation events
EventCategories.TRANSFORMATION   # "transformation"  Data transformation events
```

---

## Examples

### Basic Workflow Logging

```python
from agent_actions.logging.factory import LoggerFactory
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    WorkflowStartEvent,
    ActionStartEvent,
    ActionCompleteEvent,
    WorkflowCompleteEvent,
)

# Initialize
LoggerFactory.initialize(
    output_dir="my_workflow/agent_io",
    workflow_name="my_workflow",
)

# Workflow start
fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    action_count=3,
))

# Action 1
fire_event(ActionStartEvent(
    action_name="extract",
    action_index=0,
    total_actions=3,
))
# ... do work ...
fire_event(ActionCompleteEvent(
    action_name="extract",
    action_index=0,
    total_actions=3,
    execution_time=5.2,
))

# Workflow complete
fire_event(WorkflowCompleteEvent(
    workflow_name="my_workflow",
    elapsed_time=15.6,
    actions_completed=1,
))

# Flush
LoggerFactory.flush()
```

### Custom Event Handler

```python
from agent_actions.logging.core.manager import get_manager
from agent_actions.logging.core.events import BaseEvent

class MetricsHandler:
    def __init__(self):
        self.metrics = []

    def accepts(self, event: BaseEvent) -> bool:
        return event.category in ("workflow", "action")

    def handle(self, event: BaseEvent) -> None:
        if event.event_type == "ActionCompleteEvent":
            self.metrics.append({
                "action": event.data.get("action_name"),
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
from agent_actions.logging.core.manager import get_manager, fire_event
from agent_actions.logging.events import ActionStartEvent

manager = get_manager()

# Set global context
manager.set_context(workflow_name="main")

# All events carry workflow_name="main" in event.meta.extra
fire_event(ActionStartEvent(action_name="extract"))

# Override for nested context
with manager.context(workflow_name="upstream"):
    fire_event(ActionStartEvent(action_name="fetch"))
    # Event carries workflow_name="upstream"

# Back to workflow_name="main"
fire_event(ActionStartEvent(action_name="transform"))
```

---

## See Also

- [Logging Architecture](../reference/architecture/logging.md) - System design and flow
