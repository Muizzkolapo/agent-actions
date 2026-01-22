# TICKET-012: Add Logging System Tests

**Status:** 🔲 TODO
**Priority:** High
**Estimate:** 4-6 hours
**Labels:** logging, testing

## Description

Create comprehensive tests for the new event-based logging system.

## Deliverables

- [ ] Unit tests for core events
- [ ] Unit tests for event handlers
- [ ] Integration tests for full flow
- [ ] Tests for LoggingBridgeHandler

## Test Files to Create

```
tests/logging/
├── test_core_events.py
├── test_event_manager.py
├── test_handlers/
│   ├── test_console_handler.py
│   ├── test_json_file_handler.py
│   └── test_run_results_collector.py
├── test_logging_bridge.py
└── test_factory.py
```

## Test Cases

### Core Events

```python
def test_base_event_defaults():
    event = BaseEvent(message="test")
    assert event.level == EventLevel.INFO
    assert event.event_type == "BaseEvent"
    assert event.meta.timestamp is not None

def test_event_code_generation():
    event = WorkflowStartEvent(workflow_name="test", agent_count=1)
    assert event.code == "W001"
```

### Event Manager

```python
def test_singleton():
    m1 = EventManager.get()
    m2 = EventManager.get()
    assert m1 is m2

def test_handler_registration():
    manager = EventManager.get()
    handler = MockHandler()
    manager.register_handler(handler)
    fire_event(BaseEvent(message="test"))
    assert handler.events_received == 1
```

### Logging Bridge

```python
def test_logger_to_event():
    logger = logging.getLogger("test")
    logger.info("Hello world")
    # Verify LogEvent was fired
```

### Run Results

```python
def test_run_results_json():
    collector = RunResultsCollector("/tmp/test")
    fire_event(WorkflowStartEvent(...))
    fire_event(AgentCompleteEvent(...))
    fire_event(WorkflowCompleteEvent(...))

    results = json.load(open("/tmp/test/run_results.json"))
    assert results["metadata"]["status"] == "success"
```

## Acceptance Criteria

- [ ] >90% code coverage on logging module
- [ ] All event types have tests
- [ ] Handler behavior verified
- [ ] Integration test for full workflow
