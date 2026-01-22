# TICKET-007: Instrument Agent Executor with Events

**Status:** ✅ COMPLETED
**Priority:** High
**Completed:** January 2026
**Estimate:** 1-2 hours
**Actual:** ~1 hour
**Labels:** logging, executor, instrumentation

## Description

Instrument the agent executor to fire events for skip conditions and batch operations.

## Deliverables

- [x] Fire `AgentSkipEvent` when executor skips an agent
- [x] Fire batch-related events for batch processing
- [x] Proper event data extraction

## File Modified

```
agent_actions/workflow/executor.py
```

## Events Added

| Scenario | Event |
|----------|-------|
| Skip due to condition | `AgentSkipEvent` with reason |
| Skip due to cache | `AgentCachedEvent` |
| Batch submitted | `BatchSubmittedEvent` |
| Batch progress | `BatchProgressEvent` |
| Batch complete | `BatchCompleteEvent` |

## Skip Reasons

The executor tracks why an agent was skipped:

- `condition_not_met` - Run condition evaluated to false
- `dependency_failed` - Upstream agent failed
- `cached` - Valid cached result exists
- `disabled` - Agent is disabled in config

## Notes

- Executor handles the actual skip logic
- Coordinator orchestrates the overall workflow
- Events from both provide complete visibility
