# TICKET-003: Create Agent-Actions Event Types

**Status:** ✅ COMPLETED
**Priority:** Critical
**Completed:** January 2026
**Estimate:** 3-4 hours
**Actual:** ~3 hours
**Labels:** logging, events, domain

## Description

Create all the domain-specific event types for agent-actions workflows, agents, batches, LLM interactions, and validation.

## Deliverables

- [x] Workflow events (W001-W003)
- [x] Agent events (A001-A005)
- [x] Batch events (B001-B003)
- [x] LLM events (L001-L004)
- [x] Validation events (V001-V004)
- [x] `AgentActionsFormatter` for dbt-style console formatting

## Files Created

```
agent_actions/logging/events/
├── __init__.py
├── types.py          # All event type definitions
└── formatters.py     # AgentActionsFormatter
```

## Event Types

### Workflow Events (W prefix)

| Code | Event | Level | Description |
|------|-------|-------|-------------|
| W001 | WorkflowStartEvent | INFO | Workflow execution begins |
| W002 | WorkflowCompleteEvent | INFO | Workflow completes successfully |
| W003 | WorkflowFailedEvent | ERROR | Workflow fails |

### Agent Events (A prefix)

| Code | Event | Level | Description |
|------|-------|-------|-------------|
| A001 | AgentStartEvent | INFO | Agent starts execution |
| A002 | AgentCompleteEvent | INFO | Agent completes successfully |
| A003 | AgentSkipEvent | INFO | Agent skipped |
| A004 | AgentFailedEvent | ERROR | Agent fails |
| A005 | AgentCachedEvent | INFO | Agent result from cache |

### Batch Events (B prefix)

| Code | Event | Level | Description |
|------|-------|-------|-------------|
| B001 | BatchSubmittedEvent | INFO | Batch job submitted |
| B002 | BatchProgressEvent | DEBUG | Batch progress update |
| B003 | BatchCompleteEvent | INFO | Batch job complete |

### LLM Events (L prefix)

| Code | Event | Level | Description |
|------|-------|-------|-------------|
| L001 | LLMRequestEvent | DEBUG | LLM API request |
| L002 | LLMResponseEvent | DEBUG | LLM API response |
| L003 | LLMErrorEvent | ERROR | LLM API error |
| L004 | RateLimitEvent | WARN | Rate limit hit |

### Validation Events (V prefix)

| Code | Event | Level | Description |
|------|-------|-------|-------------|
| V001 | ValidationStartEvent | DEBUG | Validation begins |
| V002 | ValidationCompleteEvent | DEBUG | Validation complete |
| V003 | ValidationErrorEvent | ERROR | Validation error |
| V004 | ValidationWarningEvent | WARN | Validation warning |

## AgentActionsFormatter

Custom formatter that produces dbt-style output:

```python
formatter = AgentActionsFormatter(show_timestamp=True, use_color=True)
output = formatter.format(event)
# "10:30:45 | 1/5 OK extract_data in 12.34s (1700 tokens)"
```

## Usage Example

```python
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    WorkflowStartEvent,
    AgentCompleteEvent,
)

fire_event(WorkflowStartEvent(
    workflow_name="my_workflow",
    agent_count=5,
    execution_mode="parallel",
))

fire_event(AgentCompleteEvent(
    agent_name="extract_data",
    agent_index=0,
    total_agents=5,
    execution_time=12.34,
    tokens={"total_tokens": 1700},
))
```

## Notes

- All events inherit from `BaseEvent`
- Each event has a unique code (e.g., W001, A002)
- Events store structured data in `data` dict
- Message is auto-generated in `__post_init__`
