# TICKET-004: Create RunResultsCollector Handler

**Status:** ✅ COMPLETED
**Priority:** High
**Completed:** January 2026
**Estimate:** 2-3 hours
**Actual:** ~2 hours
**Labels:** logging, artifacts, ci-cd

## Description

Create the RunResultsCollector handler that generates a `run_results.json` artifact similar to dbt. This artifact enables CI/CD integration and post-execution analysis.

## Deliverables

- [x] `RunResultsCollector` event handler
- [x] `AgentResult` dataclass for agent execution data
- [x] JSON output to `target/run_results.json`
- [x] Workflow metadata collection
- [x] Agent result tracking

## Files Created

```
agent_actions/logging/events/handlers/
├── __init__.py
└── run_results.py    # RunResultsCollector + AgentResult
```

## run_results.json Schema

```json
{
  "metadata": {
    "invocation_id": "abc12345",
    "workflow_name": "my_workflow",
    "agent_count": 5,
    "execution_mode": "parallel",
    "started_at": "2026-01-22T10:30:00.000Z",
    "completed_at": "2026-01-22T10:32:08.456Z",
    "elapsed_time": 128.456,
    "status": "success"
  },
  "results": [
    {
      "unique_id": "my_workflow.extract_data",
      "agent_name": "extract_data",
      "agent_index": 0,
      "status": "success",
      "execution_time": 12.34,
      "output_folder": "/path/to/target/extract_data",
      "record_count": 150,
      "tokens": {
        "prompt_tokens": 500,
        "completion_tokens": 1200,
        "total_tokens": 1700
      },
      "timing": {
        "started_at": "2026-01-22T10:30:45.123Z",
        "completed_at": "2026-01-22T10:30:57.456Z"
      }
    }
  ],
  "elapsed_time": 128.456,
  "tokens": {
    "prompt_tokens": 2500,
    "completion_tokens": 5000,
    "total_tokens": 7500
  }
}
```

## Status Values

| Status | Description |
|--------|-------------|
| `success` | Agent/workflow completed successfully |
| `skipped` | Agent was skipped (cached or condition) |
| `cached` | Result retrieved from cache |
| `error` | Agent/workflow failed |
| `running` | Currently executing |

## Events Handled

- `WorkflowStartEvent` → Initialize metadata
- `WorkflowCompleteEvent` → Finalize and write JSON
- `WorkflowFailedEvent` → Record error and write JSON
- `AgentStartEvent` → Create agent result entry
- `AgentCompleteEvent` → Update with success data
- `AgentSkipEvent` → Record skip with reason
- `AgentCachedEvent` → Record cached result
- `AgentFailedEvent` → Record error details

## CI/CD Integration

```bash
# Check if workflow succeeded
jq -e '.metadata.status == "success"' target/run_results.json

# Get failed agents
jq '.results[] | select(.status == "error")' target/run_results.json

# Get total tokens used
jq '.tokens.total_tokens' target/run_results.json
```

## Notes

- File is written on WorkflowCompleteEvent or WorkflowFailedEvent
- Aggregates token usage across all agents
- Tracks timing for each agent
- Can be used for performance analysis
