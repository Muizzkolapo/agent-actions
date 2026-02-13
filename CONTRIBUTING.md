# Contributing to Agent Actions

Thank you for contributing to Agent Actions! This guide covers coding standards and development workflow.

## Development Setup

```bash
# Install dependencies
task dev

# Install pre-commit hooks
task hooks:install
```

## Running Quality Checks

```bash
# Run all checks
task check

# Individual checks
task lint          # ruff linting
task lint:ruff     # ruff (logging rules)
task lint:logging  # AST-based logging checker
task mypy          # type checking

# Run pre-commit on all files
task hooks:run
```

## Logging Guidelines

This project uses **f-strings** as the standard logging format for readability and consistency.

### Correct Patterns

```python
# F-strings (project standard)
logger.info(f"Processing {item_id} with value {value}")
logger.debug(f"Workflow {name} completed in {duration:.2f} seconds")
logger.warning(f"Retry attempt {attempt}/{max_retries} for {operation}")
logger.error(f"Failed to process {item_id}: {error}")

# In exception handlers, use .exception() for automatic traceback
try:
    do_something()
except Exception as e:
    logger.exception(f"Unexpected error processing {item}")  # Preferred
    # NOT: logger.error(f"Error: {e}", exc_info=True)
```

### Incorrect Patterns

```python
# BAD: Missing f-prefix with {variable} syntax
# This logs literal "{item_id}" instead of the value!
logger.info("Processing {item_id}")

# BAD: Mixed formatting styles
logger.info("Processing {item_id} with %s", value)

# BAD: Using .error() with exc_info=True in exception handlers
# Use .exception() instead
logger.error(f"Error: {e}", exc_info=True)
```

### Why This Matters

The bug pattern `logger.info("Processing {item_id}")` (missing `f` prefix) is particularly dangerous because:

1. **No exception raised** - Code runs without errors
2. **Silent failure** - Logs show `{item_id}` literally instead of the value
3. **Hard to detect** - Only visible when you read the logs carefully
4. **Wastes debugging time** - Logs are useless for troubleshooting

### Automated Detection

We use multiple tools to catch logging issues:

1. **Ruff** (`task lint:ruff`) - Catches logging anti-patterns
2. **AST Checker** (`task lint:logging`) - Detects `{var}` without f-prefix
3. **Pre-commit hooks** - Runs both on every commit

## Event-Based Logging System

agent-actions uses an event-driven architecture for user-facing output and observability.

### System Architecture

```
Application Code
       │
       ├── logger.info("msg")  ──┐
       │                         │
       └── fire_event(Event)  ───┼──► EventManager
                                 │         │
                                 │    ┌────┴────┐
                                 │    │         │
                                 ▼    ▼         ▼
                          Console  JSON File  run_results.json
```

All logging flows through the EventManager:
- Python logging (`logger.info()`) → LoggingBridgeHandler → Events
- Direct events (`fire_event()`) → Events
- Events → Handlers (Console, JSON, run_results.json)

### Adding New Event Types

Create event classes in `agent_actions/logging/events/types.py`:

```python
from agent_actions.logging.events.base import BaseEvent, EventCategory

@dataclass
class MyCustomEvent(BaseEvent):
    """Emitted when custom action occurs."""

    category: EventCategory = EventCategory.SYSTEM
    event_type: str = "custom_action"

    # Event-specific data
    action_name: str = ""
    result: str = ""

    def __post_init__(self):
        super().__post_init__()
        # Add event-specific data to the data dict
        self.data.update({
            "action_name": self.action_name,
            "result": self.result,
        })
```

Then emit the event:

```python
from agent_actions.logging import fire_event
from agent_actions.logging.events import MyCustomEvent

fire_event(MyCustomEvent(
    message="Custom action completed",
    action_name="my_action",
    result="success",
))
```

### Event Categories

Events are organized by category:

- **workflow** - Workflow lifecycle (start, complete, error)
- **agent** - Agent execution (start, complete, skip, error)
- **batch** - Batch job operations (submit, complete, error)
- **validation** - Validation events (start, pass, fail, warning)
- **progress** - Progress updates
- **system** - System-level events

### Creating Event Handlers

Implement custom handlers by extending the base handler:

```python
from agent_actions.logging.core.handlers import EventHandler

class MyHandler(EventHandler):
    def accepts(self, event: BaseEvent) -> bool:
        """Return True for events this handler should process."""
        return event.category == "workflow"

    def handle(self, event: BaseEvent) -> None:
        """Process the event."""
        print(f"Workflow event: {event.message}")

    def flush(self) -> None:
        """Flush any buffered data."""
        pass
```

Register handlers with the EventManager:

```python
from agent_actions.logging import get_manager

manager = get_manager()
manager.register(MyHandler())
```

### Testing Events

Test event emission and handling:

```python
from agent_actions.logging.core import EventManager
from agent_actions.logging.events import WorkflowStartEvent

def test_workflow_event():
    manager = EventManager.get()

    # Create mock handler
    events_received = []

    def mock_handler(event):
        events_received.append(event)

    # Register handler
    manager.register_function(mock_handler)

    # Fire event
    fire_event(WorkflowStartEvent(
        message="Test workflow",
        workflow_name="test",
    ))

    # Verify
    assert len(events_received) == 1
    assert events_received[0].workflow_name == "test"
```

### Context Propagation

Events automatically inherit context from the CorrelationContext:

```python
from agent_actions.logging import get_manager

# Set context (automatically propagates to all events)
manager = get_manager()
with manager.context(
    workflow_name="my_workflow",
    correlation_id="abc123",
):
    fire_event(AgentStartEvent(
        message="Starting agent",
        agent_name="extract_data",
    ))
    # Event will have workflow_name and correlation_id populated
```

### Event Guidelines

1. **Use typed events** - Create specific event classes, don't use BaseEvent directly
2. **Clear messages** - Event messages should be human-readable and actionable
3. **Structured data** - Put machine-readable data in the `data` dict
4. **Categories matter** - Use correct category for proper filtering
5. **Test handlers** - Write tests for custom handlers

See `agent_actions/logging/events/types.py` for all available event types.

## Testing

```bash
# Run all tests
task test

# Run with coverage
task test:coverage

# Run specific test types
task test:unit
task test:integration

# Run in parallel
task test:fast
```

## Code Style

- Python 3.11+
- 4-space indentation
- 100 character line length
- Type hints encouraged
- Run `task check` before committing

## Changelog Management

We use [changie](https://changie.dev) to manage changelog entries. Every PR that changes user-facing behavior should include a changelog entry.

### Adding a Changelog Entry

```bash
# Interactive — prompts for kind, description, and optional issue number
task changelog:new
```

This creates a YAML fragment in `.changes/unreleased/`. Commit it with your PR.

### Releasing a Version (Maintainers)

```bash
# Batch unreleased entries into a version (e.g., 2.1.0)
task changelog:batch -- 2.1.0

# Merge all versions into CHANGELOG.md
task changelog:merge
```

`changie batch` also updates the version in `pyproject.toml` and `agent_actions/__version__.py` via the replacements configured in `.changie.yaml`.

## PyPI Publishing (Maintainers)

Packages are published to PyPI automatically when a GitHub Release is created.

### Prerequisites

1. **OIDC Trusted Publishing** must be configured on [pypi.org](https://pypi.org/manage/project/agent-actions/settings/publishing/)
2. Version in git tag, `pyproject.toml`, and `agent_actions/__version__.py` must all match

### Release Steps

1. Ensure all changelog entries are batched: `task changelog:batch -- X.Y.Z`
2. Merge to `main`
3. Create a GitHub Release with tag `vX.Y.Z`
4. The `publish.yml` workflow validates versions and publishes to PyPI

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes
3. Ensure `task check` passes
4. Ensure `task test` passes
5. Submit PR with clear description
