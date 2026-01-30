---
title: Artifacts & Run Tracking
sidebar_position: 3
---

# Artifacts & Run Tracking

Agent Actions generates artifacts for debugging, auditing, and resuming interrupted runs.

## Directory Structure

```
project/
├── artefact/
│   ├── runs.json                    # Run history and metrics
│   └── rendered_workflows/          # Jinja2-rendered configs
├── logs/
│   └── agent_actions.log            # Execution logs
└── agent_workflow/
    └── my_workflow/
        └── agent_io/
            ├── .agent_status.json   # Action status tracking
            ├── staging/             # Input data
            ├── source/              # Metadata tracking
            └── target/              # Output data
                └── node_0_action_name/
```

## Run History (`artefact/runs.json`)

Tracks workflow executions with metrics:

```json
{
  "workflow_metrics": {
    "my_workflow": {
      "total_runs": 30,
      "successful_runs": 25,
      "total_tokens": 136373,
      "success_rate": 0.83
    }
  },
  "executions": [...]
}
```

## Action Status (`.agent_status.json`)

Tracks per-action execution state for resumable runs:

```json
{
  "fact_extractor": {"status": "completed"},
  "validate_output": {"status": "pending"}
}
```

| Status | Description |
|--------|-------------|
| `pending` | Not yet executed |
| `completed` | Successfully finished |
| `failed` | Terminated with error |
| `skipped` | Skipped by guard |

Re-running a workflow skips completed actions and resumes from the failure point.

## Output Record Structure

Each output record contains:

```json
{
  "source_guid": "37812c37-80a2-596b-8747-8f93e7a34e7f",
  "content": {
    "candidate_facts_list": [...]
  },
  "target_id": "dd45e6ef-63d6-45f6-8759-5df33c9a84a2",
  "node_id": "node_0_86a1e066-9522-4e0e-a3db-e83c7e38ab8c",
  "lineage": ["node_0_86a1e066-9522-4e0e-a3db-e83c7e38ab8c"]
}
```

| Field | Description |
|-------|-------------|
| `source_guid` | Links to original input record |
| `content` | Schema-validated action output |
| `target_id` | Unique identifier for this output |
| `node_id` | Action execution identifier |
| `lineage` | Chain of node_ids for provenance |

## Logs

```bash
# Set log level
AGENT_ACTIONS_LOG_LEVEL=DEBUG

# Custom log path
AGENT_ACTIONS_LOG_FILE=custom.log
```

## Useful Commands

```bash
# Check workflow success rate
jq '.workflow_metrics.my_workflow.success_rate' artefact/runs.json

# Get total tokens
jq '[.executions[].total_tokens] | add' artefact/runs.json

# Check specific node output
cat agent_io/target/node_2_transform_data/data.json | jq .
```
