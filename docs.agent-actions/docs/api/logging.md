# Logging API Reference

The complete API reference for the event-based logging system of agent-actions.

## Public API

### fire_event()

Emits an event to all registered handlers.

```python
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    action_count=5,
))
```

**Note:** Every event class sets its own `level`, `category`, `message` and `data` in `__post_init__`. If you give a `message`, the event class replaces it.

**Parameters:**
- `event` (BaseEvent): The event instance to fire

**Returns:** None

**Context Enrichment:**
Before dispatch, the EventManager copies its context into the `meta` of the event. `invocation_id` and `correlation_id` go to their own fields. Every other key goes to `meta.extra`.

---

### get_manager()

Gets the EventManager singleton instance.

```python
from agent_actions.logging.core.manager import get_manager

manager = get_manager()
manager.set_context(workflow_name="my_workflow")
```

**Returns:** EventManager instance

---

### LoggerFactory

A factory class that initializes and manages the logging system.

#### LoggerFactory.initialize()

Initializes the unified logging system with event handlers.

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
- `config` (Optional[LoggingConfig]): The logging configuration. If None, the factory keeps the configuration that an earlier call set. If there was no earlier call, the factory reads the `AGENT_ACTIONS_*` environment variables.
- `output_dir` (Optional[str | Path]): The directory whose `logs/` subdirectory receives `events.json`, `errors.json` and `run_results.json`. Defaults to None.
- `workflow_name` (str): The name of the workflow that runs. Defaults to "".
- `invocation_id` (Optional[str]): A unique ID for this invocation. If you do not give it, the factory generates an 8-character ID.
- `verbose` (Optional[bool]): Shows DEBUG level events, all categories and diagnostic events on the console. `None` (the default) keeps the value that a previous call configured. Thus a `force=True` re-init that does not give `verbose` does not discard the flags of the CLI.
- `quiet` (Optional[bool]): Shows only WARN and ERROR events on the console. `None` (the default) keeps the value that a previous call configured.
- `force` (bool): Initializes again, also if the system is already initialized. Defaults to False.
- `new_run` (bool): Marks the start of a workflow run. The run logs in `output_dir/logs` rotate first. Thus `events.json` holds only this run. Other commands append to the file of the current run. Defaults to False.

**Returns:** The EventManager instance

**Side Effects:**
- Creates and registers ProgressRenderer (the console handler of the run)
- Creates and registers two JSONFileHandler instances (if you give output_dir): `logs/events.json` at DEBUG and `logs/errors.json` at ERROR
- Creates and registers RunResultsCollector (it writes `logs/run_results.json` only if you give output_dir)
- Configures LoggingBridgeHandler to convert Python logging to events
- Sets the correlation context (invocation_id, workflow_name)

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

Gets a Python logger that routes through the event system.

```python
logger = LoggerFactory.get_logger("my_module")
logger.info("Processing item")  # Converted to LogEvent
```

**Parameters:**
- `name` (str): The logger name. If the name does not start with 'agent_actions.', the factory adds this prefix automatically.

**Returns:** A logging.Logger instance. If the factory is not initialized, the call initializes it first.

**Note:** Every record logged under the `agent_actions` namespace is converted to a LogEvent. EventManager routes the LogEvent.

#### LoggerFactory.set_context()

Sets shared context values for all events.

```python
LoggerFactory.set_context(
    workflow_name="my_workflow",
    correlation_id="abc123",
)
```

**Parameters:**
- `**kwargs`: Context key-value pairs of any kind

**Returns:** None

The context attaches automatically to all events emitted after this call, for all actions that fire them. Put a value for one action or one batch in `EventManager.context()` or in the fields of the event.

#### LoggerFactory.flush()

Flushes all event handlers (writes the buffered data).

```python
try:
    run_workflow()
finally:
    LoggerFactory.flush()  # Ensure all events are written
```

**Returns:** None

**Important:** Always call this method before the process exits. This makes sure that the buffered events are written.

#### LoggerFactory.get_event_manager()

Gets the current EventManager instance.

```python
manager = LoggerFactory.get_event_manager()
```

**Returns:** Optional[EventManager]

**Returns None if:** LoggerFactory is not initialized yet.

#### LoggerFactory.reset()

Resets the state of the factory (for tests).

```python
LoggerFactory.reset()
```

**Returns:** None

**Warning:** This method clears all handlers and the state. Use it only in tests.

---

## EventManager

The central event dispatcher. It routes events to handlers.

### EventManager.get()

Gets the EventManager singleton instance.

```python
from agent_actions.logging.core.manager import EventManager

manager = EventManager.get()
```

**Returns:** EventManager instance

---

### EventManager.initialize()

Marks the EventManager as initialized.

```python
manager.initialize()
```

**Returns:** None

**Note:** LoggerFactory.initialize() calls this method automatically.

---

### EventManager.register()

Registers an event handler.

```python
from agent_actions.logging.core.handlers import ConsoleEventHandler

handler = ConsoleEventHandler()
manager.register(handler)
```

**Parameters:**
- `handler` (EventHandler): A handler instance with `accepts()`, `handle()` and `flush()` methods. If the handler has a `close()` method, the manager calls it on reset.

**Returns:** None

---

### EventManager.unregister()

Removes a registered handler. If the handler is not registered, the method does nothing.

```python
manager.unregister(handler)
```

**Parameters:**
- `handler` (EventHandler): The handler instance to remove

**Returns:** None

---

### EventManager.fire()

Fires an event to all registered handlers.

```python
from agent_actions.logging.events import WorkflowStartEvent

event = WorkflowStartEvent(workflow_name="my_workflow", action_count=3)
manager.fire(event)
```

**Parameters:**
- `event` (BaseEvent): The event to fire

**Returns:** None

**Note:** The manager adds the context to the event before it dispatches the event.

---

### EventManager.set_context()

Sets the correlation context for all events.

```python
manager.set_context(
    workflow_name="my_workflow",
    correlation_id="abc123",
)
```

**Parameters:**
- `**kwargs`: Context key-value pairs

**Returns:** None

The values apply to the full process. Every later event in the process carries them in `meta`, for all actions that fire it. A value for one action or one batch belongs in `context()` below, or in the `data` of the event. For example, a batch id is in `data.batch_id` of the batch events.

---

### EventManager.context()

A context manager that overrides the context temporarily.

```python
with manager.context(workflow_name="upstream"):
    fire_event(WorkflowStartEvent(workflow_name="upstream", action_count=2))
    # event.meta.extra["workflow_name"] == "upstream"

# Context restored to previous value
```

The override is local to the current thread or coroutine. Calls can nest.

**Parameters:**
- `**kwargs`: Temporary context values

**Returns:** Context manager

**Yields:** None

---

### EventManager.flush()

Flushes all registered handlers.

```python
manager.flush()
```

**Returns:** None

---

### EventManager.reset()

Resets the state of the EventManager (for tests).

```python
EventManager.reset()
```

**Returns:** None

**Warning:** This method clears all handlers and the context. Use it only in tests.

---

## Event Classes

All event classes inherit from `BaseEvent`. All event classes are dataclasses.

### BaseEvent

The base class for all events.

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
- `level` (EventLevel): The severity
- `category` (str): The event category. See [EventCategories](#eventcategories)
- `message` (str): A message that a person can read
- `meta` (EventMeta): `timestamp`, `correlation_id`, `invocation_id`, `thread_id` and `extra` (the other context keys)
- `data` (Dict[str, Any]): Structured event data
- `diagnostic` (bool): Marks framework internals, not something that the user can act on. The file handlers keep these events. The console drops them, unless the run is verbose
- `event_type` (str, read-only property): The event class name, such as `"ActionStartEvent"`

---

### Workflow Events

#### WorkflowStartEvent

Emitted when a workflow starts to run.

```python
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    action_count=5,
    execution_mode="async",
))
```

**Note:** The event class generates the `message` field from `workflow_name` and `action_count`.

**Fields:**
- `workflow_name` (str): Workflow name
- `action_count` (int): The number of actions in the workflow
- `execution_mode` (str): `"sequential"` or `"async"`. The workflow runner sets it. It defaults to `"sequential"`

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
- `elapsed_time` (float): The total execution time in seconds
- `actions_completed` (int): The number of actions that completed
- `actions_partial` (int): The number of actions that completed with failed records
- `actions_skipped` (int): The number of actions that were skipped
- `actions_failed` (int): The number of actions that failed
- `total_tokens` (int): The total number of tokens used
- `records_failed_checks` (int): The records that the actions of the workflow hold and that shipped with an expectations verdict whose `overall_pass` is false. Agent Actions reads the count from the store when the run ends. If a batch workflow completes over several runs, the count includes the records that the earlier runs collected. When the value is above zero, the workflow line turns to `⚠` and says `N records failed their checks`

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
- `error_message` (str): The description of the error
- `error_detail` (str): More detail about the error
- `error_type` (str): The name of the exception type
- `elapsed_time` (float): The time elapsed before the failure
- `failed_action` (str): The name of the action that failed

---

#### StepStartEvent

Emitted when a dependency level starts. The event fires also when no action in the level is pending.

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
- `step_index` (int): The position of the level, 0-based (shown 1-based)
- `total_steps` (int): The number of levels in the run
- `actions` (List[str]): Every action in the level
- `pending` (List[str]): The subset of actions that will actually run

---

#### StepCompleteEvent

Emitted when a dependency level ends, for all outcomes.

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
- `elapsed_time` (float): The wall time of the level
- `completed` / `partial` / `skipped` / `failed` / `unfinished` (int): The number of actions for each outcome. Their sum is the size of the level
- `batch_pending` (List[str]): The actions whose batch jobs are not complete yet. If the list is not empty, the level paused and did not finish

---

### Action Events

#### ActionStartEvent

Emitted when an action starts to process.

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
- `action_index` (int): The position of the action in the workflow (0-based)
- `total_actions` (int): The total number of actions
- `action_type` (str): The kind of the action (`"llm"`, `"tool"`, `"hitl"`)
- `input_path` (str): The path to the input file
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
- `action_index` (int): The position of the action in the workflow (0-based)
- `total_actions` (int): The total number of actions
- `execution_time` (float): The execution time in seconds
- `output_path` (str): The path to the output file
- `record_count` (int): The number of records that this execution produced. If a run replaces records that are already stored, the count includes them again. Thus `agac run --rerun` and `agac retry` report the records that they answered. The count does not include records carried forward from an earlier run. The `✓ <action>  N records` completion line shows the same number.
- `guard_skipped` (int): The part of `record_count` that the guard of the action skipped in this execution. Agent Actions keeps these records as tombstones. When the value is above zero, the completion line ends with `— N skipped by guard`.
- `checks_failed` (int): The records that this execution shipped with an expectations verdict whose `overall_pass` is false (`on_exhausted: return_last`, `repair: none`). Agent Actions stores them as successes. When the value is above zero, the completion line turns to `⚠` and says `N failed their checks`.
- `tokens` (Dict[str, int]): The token usage, item by item
- `mode` (str): `"online"` or `"batch"`
- `model_vendor` / `model_name` (str): The model that ran the action. Empty for a tool action or a HITL action
- `kind` (str): `"llm"`, `"tool"`, `"hitl"`, … — consumers use it to decide if a model is meaningful

---

#### ActionSkipEvent

Emitted when an action is skipped. For example, the guard condition of the action filters every record.

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
- `action_index` (int): The position of the action in the workflow (0-based)
- `total_actions` (int): The total number of actions
- `skip_reason` (str): The reason why the action was skipped
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
- `action_index` (int): The position of the action in the workflow (0-based)
- `total_actions` (int): The total number of actions
- `error_message` (str): The description of the error
- `error_detail` (str): More detail about the error
- `error_type` (str): The name of the exception class
- `execution_time` (float): The time elapsed before the failure
- `suggestion` (str): A suggested fix or the next step
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
- `batch_id` (str): The ID of the batch job
- `action_name` (str): Action name
- `request_count` (int): The number of requests in the batch
- `provider` (str): The LLM provider

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
- `batch_id` (str): The ID of the batch job
- `action_name` (str): Action name
- `total` (int): The total number of requests in the batch
- `completed` (int): The number of requests that completed successfully
- `failed` (int): The number of requests that failed
- `elapsed_time` (float): The total time in seconds
- `total_tokens` (int): The total number of tokens used

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
- `error_message` (str): The description of the error
- `error_type` (str): The name of the exception class

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
- `target` (str): The item that is validated
- `validator` (str): The name of the validator

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
- `target` (str): The item that was validated
- `validator` (str): The name of the validator
- `elapsed_time` (float): The validation time in seconds
- `warning_count` (int): The number of warnings found
- `error_count` (int): The number of errors found. When this value is not 0, the level of the event is ERROR

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
- `target` (str): The item that was validated
- `field` (str): The field that failed
- `error` (str): The description of the error
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
- `target` (str): The item that was validated
- `field` (str): The field that caused the warning
- `warning` (str): The warning message
- `value` (Any): The value that caused the problem (optional)

---

## Event Handlers

### EventHandler (Base Class)

The base class for all event handlers.

`EventHandler` is a `Protocol` in `agent_actions.logging.core.protocols`. A handler is any object with these methods. A handler does not need to subclass `EventHandler`.

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
- `accepts(event)` → bool: Returns True if the handler processes this event
- `handle(event)` → None: Processes the event
- `flush()` → None: Flushes the buffered data
- `close()` → None: Releases resources. The protocol lists this method. If the handler has it, the manager calls it on reset and on a forced re-initialize

---

### ProgressRenderer

The console handler that a run installs. It is a subclass of `ConsoleEventHandler`. It shows
workflow, step and action events as a progress stream, grouped by step. All
other events use the formatting below.

```python
from agent_actions.logging.core.handlers import ProgressRenderer
```

Takes the same parameters as `ConsoleEventHandler`.

---

### ConsoleEventHandler

Writes events to the console (stderr). When Rich is available, it uses Rich formatting.

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
- `min_level` (EventLevel): The minimum event level to show. Defaults to `EventLevel.INFO`
- `show_timestamp` (bool): Includes the timestamp in the output. Defaults to True
- `formatter` (Optional[Callable]): A custom formatter function. It takes an event and returns a string
- `console` (Optional[Any]): The Rich console to write to. Defaults to a Rich console on stderr
- `categories` (Optional[Set[str]]): The event categories to show (None = all). WARN and ERROR events show for all categories
- `show_diagnostics` (bool): Shows events marked diagnostic. Defaults to False, which drops them at all levels

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
- `file_path` (str | Path): The path of the output file. The handler creates the parent directories
- `min_level` (EventLevel): The minimum event level to log. Defaults to `EventLevel.DEBUG`
- `buffer_size` (int): The number of events to buffer before a write. Defaults to 10
- `max_debug_bytes` (Optional[int]): When the file is larger than this number of bytes, the handler stops writing DEBUG events. Defaults to None (no limit)
- `include_all_fields` (bool): True writes the full dictionary of each event. False writes only `event_type`, `level`, `message` and `timestamp`. Defaults to True

**Output Format:** NDJSON (one JSON object on each line)

---

### RunResultsCollector

Collects the execution results of the workflow into run_results.json.

```python
from agent_actions.logging.events.handlers import RunResultsCollector

collector = RunResultsCollector(
    output_dir="/path/to/agent_io",
    workflow_name="my_workflow",
)
```

**Parameters:**
- `output_dir` (Optional[str | Path]): The directory to write run_results.json to
- `workflow_name` (str): The name of the workflow that runs

**Output:** `{output_dir}/logs/run_results.json`

**Methods:**
- `accepts(event)`: Returns True for events in the workflow and action categories, and for `RecordEmptyOutputEvent` and `ResultCollectionCompleteEvent`
- `handle(event)`: Processes the event and updates the internal state
- `flush()`: Writes run_results.json to disk

---

## Configuration

### LoggingConfig

The settings for the logging system.

```python
from agent_actions.logging.config import LoggingConfig

config = LoggingConfig(default_level="INFO")

LoggerFactory.initialize(config=config)
```

**Fields:**
- `default_level` (str): The default log level ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"). `from_environment()` reads it from `AGENT_ACTIONS_LOG_LEVEL`. `AGENT_ACTIONS_DEBUG=1` forces `"DEBUG"`
- `module_levels` (dict): Level overrides for each logger, applied at init. The keys are
  Python logger names (for example, `"httpx"`, `"my_module"`). The values are level
  strings. Use this field to enable again a logger that the framework clamps by default.
  You can also use it to silence a logger that still writes too many messages.
- `file_handler` (FileHandlerSettings): `max_bytes` and `backup_count` set the size and the rotation
  of the run log. See [File Handler](#filehandlersettings) below

#### Third-party logger suppression

`LoggerFactory.initialize()` clamps a curated set of SDK / HTTP loggers to `WARNING` on every init.
Thus the CLI shows mainly the output of the framework. The curated set is:

```
httpx, httpcore, urllib3, openai, anthropic, ollama, groq,
cohere, google_genai, googleapiclient, sentence_transformers,
transformers, pypdf
```

To get verbose output again from one of these loggers, pass `module_levels` when you construct the config.
You can also use `module_levels` to silence a logger that is not in the curated list:

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

Overrides on `agent_actions` and on all of its children are refused, with a
warning on stderr. The framework root must stay at DEBUG, so that every event gets to
`events.json`. To set the level that the CLI shows, use `default_level`.

From the CLI, set the same values under `logging.module_levels` in
`agent_actions.yml`. At boot, the CLI builds its config with
`LoggingConfig.from_environment(LoggingConfig.from_project_config(project_config))`.
Thus the project block is the base. A set `AGENT_ACTIONS_*` variable
overrides only its own key. `module_levels` has no environment form. See
[Configuration](../reference/configuration#project-configuration).

#### FileHandlerSettings

`LoggingConfig.file_handler` is a `FileHandlerSettings` with two fields.
`LoggerFactory` reads the two fields:

- `max_bytes` (`logging.file.max_bytes` / `AGENT_ACTIONS_LOG_MAX_BYTES`) sets the
  limit on the DEBUG rows written to each run file.
- `backup_count` (`logging.file.backup_count` / `AGENT_ACTIONS_LOG_RETAIN_RUNS`) sets
  the number of earlier runs to keep.

Only the `output_dir` passed to `LoggerFactory.initialize()` decides if a run-log file
handler is registered, and where it writes. The file is always `events.json` at DEBUG.

All other `logging.file.*` project keys configure nothing. The
`AGENT_ACTIONS_NO_LOG_FILE`, `AGENT_ACTIONS_LOG_FILE`, `AGENT_ACTIONS_LOG_DIR`, `AGENT_ACTIONS_FILE_LOG_LEVEL`
and `AGENT_ACTIONS_LOG_FORMAT` env vars also configure nothing. If one of these is set, the CLI reports
it on stderr at boot and ignores it (see the File Handler section of the architecture doc).

---

## Constants

### EventLevel

The event severity levels.

```python
from agent_actions.logging.core.events import EventLevel

EventLevel.DEBUG    # Detailed diagnostic information
EventLevel.INFO     # General informational messages
EventLevel.WARN     # Warning messages
EventLevel.ERROR    # Error messages
```

---

### EventCategories

The event category strings for filters. `event.category` holds one of these values.

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
