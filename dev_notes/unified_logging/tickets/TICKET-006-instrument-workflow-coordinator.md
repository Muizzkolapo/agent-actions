# TICKET-006: Instrument Workflow Coordinator with Events

**Status:** ✅ COMPLETED
**Priority:** High
**Completed:** January 2026
**Estimate:** 2-3 hours
**Actual:** ~2 hours
**Labels:** logging, workflow, instrumentation

## Description

Instrument the workflow coordinator to fire events at key execution points. This provides visibility into workflow execution flow.

## Deliverables

- [x] Fire `WorkflowStartEvent` at workflow begin
- [x] Fire `AgentStartEvent` when agent begins
- [x] Fire `AgentCompleteEvent` on success
- [x] Fire `AgentFailedEvent` on failure
- [x] Fire `AgentSkipEvent` when skipped
- [x] Fire `WorkflowCompleteEvent` at end
- [x] Fire `WorkflowFailedEvent` on workflow error

## File Modified

```
agent_actions/workflow/coordinator.py
```

## Changes Made

### Imports Added

```python
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    WorkflowStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    AgentStartEvent,
    AgentCompleteEvent,
    AgentFailedEvent,
    AgentSkipEvent,
)
```

### Methods Updated

| Method | Event Fired |
|--------|-------------|
| `_log_workflow_start()` | `WorkflowStartEvent` |
| `_run_single_agent()` | `AgentStartEvent` |
| `_log_agent_skip()` | `AgentSkipEvent` |
| `_log_agent_result()` | `AgentCompleteEvent` or `AgentFailedEvent` |
| `_finalize_workflow()` | `WorkflowCompleteEvent` |
| `_handle_workflow_error()` | `WorkflowFailedEvent` |

## Example Event Flow

```
WorkflowStartEvent(workflow_name="my_workflow", agent_count=3)
  └─ AgentStartEvent(agent_name="extract", agent_index=0, total_agents=3)
  └─ AgentCompleteEvent(agent_name="extract", execution_time=12.5, tokens={...})
  └─ AgentStartEvent(agent_name="transform", agent_index=1, total_agents=3)
  └─ AgentCompleteEvent(agent_name="transform", execution_time=8.2, tokens={...})
  └─ AgentStartEvent(agent_name="load", agent_index=2, total_agents=3)
  └─ AgentCompleteEvent(agent_name="load", execution_time=5.1, tokens={...})
WorkflowCompleteEvent(workflow_name="my_workflow", elapsed_time=25.8, tokens={...})
```

## Notes

- Events fire in addition to existing logging (which gets bridged to events)
- Token usage is extracted from agent results
- Execution time is calculated from start/end timestamps
- Agent index is 0-based for consistency
