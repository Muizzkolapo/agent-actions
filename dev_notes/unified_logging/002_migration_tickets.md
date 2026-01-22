# Unified Logging Migration Tickets

These tickets describe the remaining work to complete the migration to the unified event-based logging system.

---

## TICKET-001: Remove console.print() calls from workflow modules

**Priority:** High
**Estimate:** 2-3 hours
**Labels:** logging, migration, cleanup

### Description

Replace remaining `console.print()` calls with appropriate event firing. The coordinator and executor have been partially migrated, but there are still direct console.print calls for:
- UDF discovery messages
- Execution mode messages

### Files to Update

```
agent_actions/workflow/coordinator.py
agent_actions/workflow/executor.py
agent_actions/workflow/parallel/action_executor.py
```

### Tasks

- [ ] Search for `console.print` in workflow modules
- [ ] Create new event types if needed (e.g., `UDFDiscoveredEvent`)
- [ ] Replace console.print with fire_event calls
- [ ] Test output is still user-friendly

### Acceptance Criteria

- No direct console.print calls in workflow modules
- All user-facing output goes through events
- Console output format unchanged from user perspective

---

## TICKET-002: Add events to LLM provider layer

**Priority:** High
**Estimate:** 4-6 hours
**Labels:** logging, llm, events

### Description

Instrument the LLM provider layer to fire events for API requests, responses, and errors. This enables tracking of token usage, latency, and rate limits.

### Event Types to Use

```python
from agent_actions.logging.events import (
    LLMRequestEvent,   # L001 - Before API call
    LLMResponseEvent,  # L002 - After successful response
    LLMErrorEvent,     # L003 - On API error
    RateLimitEvent,    # L004 - On rate limit
)
```

### Files to Update

```
agent_actions/llm/providers/base.py
agent_actions/llm/providers/anthropic_provider.py
agent_actions/llm/providers/openai_provider.py
agent_actions/llm/providers/gemini_provider.py
agent_actions/llm/realtime/processor.py
```

### Tasks

- [ ] Add `fire_event(LLMRequestEvent(...))` before API calls
- [ ] Add `fire_event(LLMResponseEvent(...))` after successful responses
- [ ] Add `fire_event(LLMErrorEvent(...))` in error handlers
- [ ] Add `fire_event(RateLimitEvent(...))` in retry logic
- [ ] Include token counts, latency, model info in events

### Example Implementation

```python
from agent_actions.logging import fire_event
from agent_actions.logging.events import LLMRequestEvent, LLMResponseEvent

def call_api(self, messages, model):
    start = time.time()

    fire_event(LLMRequestEvent(
        provider=self.provider_name,
        model=model,
        agent_name=self.current_agent,
        prompt_tokens=self._estimate_tokens(messages),
    ))

    response = self._make_request(messages, model)
    latency = (time.time() - start) * 1000

    fire_event(LLMResponseEvent(
        provider=self.provider_name,
        model=model,
        agent_name=self.current_agent,
        completion_tokens=response.usage.completion_tokens,
        total_tokens=response.usage.total_tokens,
        latency_ms=latency,
    ))

    return response
```

### Acceptance Criteria

- All LLM API calls fire request/response events
- Errors fire LLMErrorEvent with error details
- Rate limits fire RateLimitEvent with retry info
- Token usage tracked in events

---

## TICKET-003: Add events to batch processing

**Priority:** High
**Estimate:** 3-4 hours
**Labels:** logging, batch, events

### Description

Instrument batch processing to fire events for job lifecycle. Some batch events are already fired from executor.py, but the batch service itself should fire more detailed events.

### Files to Update

```
agent_actions/llm/batch/service.py
agent_actions/llm/batch/services/processing.py
agent_actions/llm/batch/services/submission.py
agent_actions/llm/batch/services/retrieval.py
```

### Tasks

- [ ] Fire `BatchSubmittedEvent` when job is submitted to provider
- [ ] Fire `BatchProgressEvent` during polling (with completed/total counts)
- [ ] Fire `BatchCompleteEvent` when job finishes
- [ ] Include batch_id, request_count, provider info

### Acceptance Criteria

- Batch job lifecycle fully tracked via events
- Progress updates visible in verbose mode
- Batch completion status in run_results.json

---

## TICKET-004: Add events to validation layer

**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** logging, validation, events

### Description

Instrument the validation layer to fire events for validation results. This helps users understand what validations passed/failed.

### Event Types to Use

```python
from agent_actions.logging.events import (
    ValidationStartEvent,    # V001
    ValidationCompleteEvent, # V002
    ValidationErrorEvent,    # V003
    ValidationWarningEvent,  # V004
)
```

### Files to Update

```
agent_actions/validation/preflight.py
agent_actions/validation/prompt_validator.py
agent_actions/validation/run_validator.py
agent_actions/validation/static_analysis.py
```

### Tasks

- [ ] Fire ValidationStartEvent at validation start
- [ ] Fire ValidationErrorEvent for each error found
- [ ] Fire ValidationWarningEvent for each warning
- [ ] Fire ValidationCompleteEvent with summary

### Acceptance Criteria

- Validation errors/warnings visible in console output
- Validation events captured in events.json
- Clear error messages with field names and suggestions

---

## TICKET-005: Remove deprecated logging infrastructure

**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** logging, cleanup, tech-debt

### Description

Remove the old logging infrastructure that's no longer needed now that everything routes through events.

### Files to Update/Remove

```
agent_actions/logging/formatters.py      # May be removable
agent_actions/logging/filters.py         # Keep ContextInjectingFilter for now
```

### Tasks

- [ ] Audit which formatters are still used
- [ ] Remove HumanFormatter, SimpleFormatter if unused
- [ ] Keep JSONFormatter if used by StructuredLogHandler
- [ ] Update imports throughout codebase
- [ ] Remove unused config options from LoggingConfig

### Acceptance Criteria

- No dead code in logging module
- All imports resolve correctly
- Tests pass

---

## TICKET-006: Update logging tests

**Priority:** High
**Estimate:** 4-6 hours
**Labels:** logging, testing

### Description

Update the test suite to cover the new event-based logging system.

### Test Files to Create/Update

```
tests/logging/test_event_manager.py
tests/logging/test_event_types.py
tests/logging/test_handlers.py
tests/logging/test_bridge.py
tests/logging/test_factory.py
```

### Tasks

- [ ] Test EventManager singleton behavior
- [ ] Test event creation and serialization
- [ ] Test ConsoleEventHandler output formatting
- [ ] Test JSONFileHandler writes correct NDJSON
- [ ] Test RunResultsCollector generates correct artifact
- [ ] Test LoggingBridgeHandler converts Python logs to events
- [ ] Test LoggerFactory unified initialization
- [ ] Integration test: full workflow with event capture

### Example Test

```python
def test_workflow_events_captured():
    """Test that workflow execution fires correct events."""
    from agent_actions.logging.core import EventManager

    captured_events = []

    class CapturingHandler:
        def accepts(self, event): return True
        def handle(self, event): captured_events.append(event)
        def flush(self): pass

    manager = EventManager.get()
    manager.register(CapturingHandler())

    # Run workflow...

    # Assert events captured
    event_types = [e.event_type for e in captured_events]
    assert "WorkflowStartEvent" in event_types
    assert "AgentStartEvent" in event_types
    assert "AgentCompleteEvent" in event_types
    assert "WorkflowCompleteEvent" in event_types
```

### Acceptance Criteria

- 80%+ test coverage on logging/core/
- All event types tested
- Integration tests for event flow

---

## TICKET-007: Add --verbose and --quiet CLI flags

**Priority:** Low
**Estimate:** 1-2 hours
**Labels:** cli, logging, feature

### Description

Expose verbose/quiet logging options via CLI flags on the run command.

### Files to Update

```
agent_actions/cli/run.py
agent_actions/cli/main.py
```

### Tasks

- [ ] Add `--verbose` flag to run command (shows DEBUG events)
- [ ] Add `--quiet` flag to run command (shows only WARN/ERROR)
- [ ] Pass flags through to LoggerFactory.initialize()
- [ ] Update help text

### Example

```bash
# Verbose mode - see all events including debug
agac run -a my_workflow --verbose

# Quiet mode - only see warnings and errors
agac run -a my_workflow --quiet
```

### Acceptance Criteria

- --verbose shows all events including debug/system
- --quiet only shows warnings and errors
- Default behavior unchanged

---

## TICKET-008: Documentation for new logging system

**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** documentation

### Description

Create user-facing documentation for the new logging system.

### Documentation to Create

```
docs/logging.md           # User guide
docs/events.md            # Event reference
docs/run_results.md       # run_results.json schema
```

### Tasks

- [ ] Document how to use fire_event()
- [ ] Document all event types with examples
- [ ] Document run_results.json schema
- [ ] Document CLI logging flags
- [ ] Add examples for custom event handlers

### Acceptance Criteria

- Clear documentation for event-based logging
- Examples for common use cases
- run_results.json schema documented

---

## TICKET-009: Add events to error handling

**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** logging, errors, events

### Description

Integrate the error translation system with events so that user-friendly errors are captured as events.

### Files to Update

```
agent_actions/logging/errors/translator.py
agent_actions/logging/errors/user_error.py
agent_actions/cli/utils/error_handler.py
```

### Tasks

- [ ] Fire AgentFailedEvent with error suggestion from ErrorTranslator
- [ ] Fire WorkflowFailedEvent with formatted error message
- [ ] Include fix suggestions in event data
- [ ] Ensure errors appear in run_results.json

### Acceptance Criteria

- Failed agents have error details in run_results.json
- Error suggestions included in events
- User-friendly messages in console output

---

## TICKET-010: Performance optimization for high-volume events

**Priority:** Low
**Estimate:** 3-4 hours
**Labels:** logging, performance

### Description

Optimize event system for high-volume scenarios (many agents, batch processing).

### Tasks

- [ ] Add event buffering option for batch processing
- [ ] Implement async event firing option
- [ ] Add event sampling for debug events
- [ ] Profile event overhead
- [ ] Consider using `fire_event_if` pattern from dbt for expensive events

### Example (dbt pattern)

```python
# Only construct event if DEBUG level is enabled
if manager.should_fire_debug():
    fire_event(DebugEvent(
        message="Expensive debug info",
        detail=self._compute_expensive_detail(),
    ))
```

### Acceptance Criteria

- No noticeable performance regression
- High-volume batch processing works smoothly
- Option to disable verbose events

---

## Summary

| Ticket | Priority | Estimate | Description |
|--------|----------|----------|-------------|
| TICKET-001 | High | 2-3h | Remove console.print from workflow |
| TICKET-002 | High | 4-6h | Add events to LLM providers |
| TICKET-003 | High | 3-4h | Add events to batch processing |
| TICKET-004 | Medium | 2-3h | Add events to validation |
| TICKET-005 | Medium | 2-3h | Remove deprecated logging code |
| TICKET-006 | High | 4-6h | Update logging tests |
| TICKET-007 | Low | 1-2h | Add --verbose/--quiet CLI flags |
| TICKET-008 | Medium | 2-3h | Documentation |
| TICKET-009 | Medium | 2-3h | Events for error handling |
| TICKET-010 | Low | 3-4h | Performance optimization |

**Total Estimated Effort:** 26-37 hours

**Recommended Order:**
1. TICKET-006 (Tests) - Ensure stability
2. TICKET-001 (Workflow cleanup) - Complete core migration
3. TICKET-002 (LLM events) - High value
4. TICKET-003 (Batch events) - High value
5. TICKET-004 (Validation events)
6. TICKET-009 (Error events)
7. TICKET-005 (Cleanup)
8. TICKET-007 (CLI flags)
9. TICKET-008 (Docs)
10. TICKET-010 (Performance)
