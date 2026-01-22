# Developer Quick Reference - Event-Based Logging

## TL;DR

```python
# OLD WAY (still works but deprecated for user-facing output)
logger.info("Starting workflow")
console.print("[green]OK[/green] agent completed")

# NEW WAY
from agent_actions.logging import fire_event
from agent_actions.logging.events import WorkflowStartEvent, AgentCompleteEvent

fire_event(WorkflowStartEvent(workflow_name="test", agent_count=5))
fire_event(AgentCompleteEvent(agent_name="extract", agent_index=0, total_agents=5, execution_time=12.5))
```

## When to Use What

| Scenario | Use |
|----------|-----|
| User should see it | `fire_event()` with typed event |
| Debug/internal info | `logger.debug()` (auto-bridged) |
| Error user should see | `fire_event(AgentFailedEvent(...))` |
| Temporary debugging | `logger.debug()` or `print()` |

## Common Events

### Workflow Lifecycle

```python
from agent_actions.logging.events import (
    WorkflowStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
)

# Start
fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    agent_count=5,
    execution_mode="parallel",  # or "sequential"
))

# Success
fire_event(WorkflowCompleteEvent(
    workflow_name="my_workflow",
    elapsed_time=83.5,
    agents_completed=4,
    agents_skipped=1,
    agents_failed=0,
))

# Failure
fire_event(WorkflowFailedEvent(
    workflow_name="my_workflow",
    error_message="Connection timeout",
    error_type="TimeoutError",
    elapsed_time=30.0,
    failed_agent="extract_data",
))
```

### Agent Lifecycle

```python
from agent_actions.logging.events import (
    AgentStartEvent,
    AgentCompleteEvent,
    AgentSkipEvent,
    AgentFailedEvent,
)

# Start
fire_event(AgentStartEvent(
    agent_name="extract_data",
    agent_index=0,
    total_agents=5,
    agent_type="llm",
))

# Success
fire_event(AgentCompleteEvent(
    agent_name="extract_data",
    agent_index=0,
    total_agents=5,
    execution_time=12.34,
    output_path="/path/to/output",
    tokens={"prompt_tokens": 500, "completion_tokens": 1200, "total_tokens": 1700},
))

# Skip
fire_event(AgentSkipEvent(
    agent_name="transform",
    agent_index=1,
    total_agents=5,
    skip_reason="already completed",  # or "WHERE clause condition not met"
))

# Failure
fire_event(AgentFailedEvent(
    agent_name="extract_data",
    agent_index=0,
    total_agents=5,
    error_message="API rate limit exceeded",
    error_type="RateLimitError",
    execution_time=5.2,
    suggestion="Wait 60 seconds and retry",
))
```

### LLM Events

```python
from agent_actions.logging.events import (
    LLMRequestEvent,
    LLMResponseEvent,
    LLMErrorEvent,
    RateLimitEvent,
)

# Request
fire_event(LLMRequestEvent(
    provider="anthropic",
    model="claude-3-opus",
    agent_name="extract_data",
    prompt_tokens=500,
))

# Response
fire_event(LLMResponseEvent(
    provider="anthropic",
    model="claude-3-opus",
    agent_name="extract_data",
    completion_tokens=1200,
    total_tokens=1700,
    latency_ms=2500,
))

# Error
fire_event(LLMErrorEvent(
    provider="anthropic",
    model="claude-3-opus",
    agent_name="extract_data",
    error_message="Invalid API key",
    error_type="AuthenticationError",
    retry_count=0,
))

# Rate limit
fire_event(RateLimitEvent(
    provider="anthropic",
    retry_after=60.0,
    agent_name="extract_data",
))
```

### Batch Events

```python
from agent_actions.logging.events import (
    BatchSubmittedEvent,
    BatchProgressEvent,
    BatchCompleteEvent,
)

# Submitted
fire_event(BatchSubmittedEvent(
    batch_id="batch_abc123",
    agent_name="extract_data",
    request_count=100,
    provider="anthropic",
))

# Progress (DEBUG level - only in verbose mode)
fire_event(BatchProgressEvent(
    batch_id="batch_abc123",
    completed=50,
    total=100,
    failed=2,
))

# Complete
fire_event(BatchCompleteEvent(
    batch_id="batch_abc123",
    agent_name="extract_data",
    completed=98,
    failed=2,
    elapsed_time=300.5,
    total_tokens=50000,
))
```

## Creating Custom Events

```python
from dataclasses import dataclass
from agent_actions.logging.core.events import BaseEvent, EventLevel

@dataclass
class MyCustomEvent(BaseEvent):
    """Custom event for my feature."""

    my_field: str = ""
    my_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = "custom"  # Shows on console if in categories filter
        self.message = f"Custom event: {self.my_field} ({self.my_count})"
        self.data = {
            "my_field": self.my_field,
            "my_count": self.my_count,
        }

    @property
    def code(self) -> str:
        return "C001"  # Custom code

# Usage
fire_event(MyCustomEvent(my_field="test", my_count=42))
```

## Console Output Format

Events produce dbt-style console output:

```
HH:MM:SS | LEVEL | message
```

Examples:
```
10:30:45 | Running workflow my_workflow (5 agents)
10:30:46 | 1/5 START extract_data
10:30:58 | 1/5 OK extract_data in 12.34s (1700 tokens)
10:31:00 | 2/5 SKIP transform (already completed)
10:31:05 | 3/5 ERROR load_data: Connection refused
           Suggestion: Check database connection
10:32:08 | Completed in 83.45s | 4 OK | 1 SKIP | 0 ERROR
```

## Filtering by Category

By default, console shows only: `workflow`, `agent`, `batch`

In verbose mode (`--verbose`), shows all categories including `llm`, `validation`, `debug`, `log`.

## Artifacts Generated

| File | Content |
|------|---------|
| `target/events.json` | All events in NDJSON format |
| `target/run_results.json` | Workflow execution summary |

## Testing Events

```python
def test_my_feature_fires_events():
    from agent_actions.logging.core import EventManager

    captured = []

    class CaptureHandler:
        def accepts(self, e): return True
        def handle(self, e): captured.append(e)
        def flush(self): pass

    EventManager.get().register(CaptureHandler())

    # Run your code...

    # Assert
    assert any(e.event_type == "MyCustomEvent" for e in captured)
```

## Debugging

```python
# See all events including debug
LoggerFactory.initialize(verbose=True)

# Check what events were fired
manager = LoggerFactory.get_event_manager()
# Events are passed to handlers, not stored

# Force flush to file
LoggerFactory.flush()
```
