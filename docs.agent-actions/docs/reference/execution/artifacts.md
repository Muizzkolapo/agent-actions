---
title: Artifacts & Run Tracking
sidebar_position: 3
---

# Artifacts & Run Tracking

Agent Actions generates artifacts for debugging, auditing, and resuming interrupted runs. Understanding this structure helps you inspect what happened during execution and diagnose issues.

## Complete Directory Structure

```
project/
├── artefact/
│   ├── catalog.json                    # Project catalog (agac docs)
│   ├── runs.json                       # Workflow execution history (agac run + agac docs)
│   └── rendered_workflows/             # Partial rendered configs saved when preflight render fails
├── logs/
│   └── agent_actions.log              # Application logs
└── agent_workflow/
    └── my_workflow/
        └── agent_io/
            ├── .agent_status.json      # Per-action execution state
            ├── staging/                # Input data
            ├── source/                 # Source metadata tracking
            ├── store/
            │   └── {workflow_name}.db  # SQLite storage backend
            ├── logs/
            │   ├── .manifest.json      # Workflow execution manifest
            │   ├── run_results.json    # Summary metrics and timing
            │   ├── events.json         # Full event telemetry (JSON Lines)
            │   └── errors.json         # Error-level events only (JSON Lines)
            └── target/
                └── {action_name}/      # Per-action output directories
```

## Runtime Artifacts

### Workflow Manifest (`.manifest.json`)

**Path:** `agent_io/logs/.manifest.json`

The manifest tracks the execution plan and status for the entire workflow run. Created when the workflow starts, updated as actions complete.

```json
{
  "schema_version": "1.0",
  "workflow_name": "product_pipeline",
  "workflow_run_id": "run_abc123",
  "started_at": "2026-03-24T10:00:00Z",
  "completed_at": "2026-03-24T10:02:30Z",
  "status": "completed",
  "execution_order": ["extract_data", "generate_content"],
  "levels": [[0, "extract_data"], [1, "generate_content"]],
  "actions": {
    "extract_data": {
      "status": "completed",
      "output_dir": "extract_data",
      "dependencies": [],
      "record_count": 5,
      "started_at": "2026-03-24T10:00:01Z",
      "completed_at": "2026-03-24T10:01:15Z"
    }
  }
}
```

The VS Code Workflow Navigator reads this file to display the sidebar tree view and DAG visualization.

### Action Status (`.agent_status.json`)

**Path:** `agent_io/.agent_status.json`

Persists per-action execution state for resumable runs:

```json
{
  "extract_data": {"status": "completed"},
  "generate_content": {"status": "completed"},
  "validate_output": {"status": "pending"}
}
```

| Status | Description |
|--------|-------------|
| `pending` | Not yet executed |
| `running` | Currently executing |
| `completed` | Successfully finished |
| `failed` | Terminated with error |
| `skipped` | Skipped by guard |
| `batch_submitted` | Batch job submitted, awaiting results |

Re-running a workflow skips completed actions and resumes from the failure point.

### Run Results (`run_results.json`)

**Path:** `agent_io/logs/run_results.json`

Summary of the workflow execution with per-action metrics:

```json
{
  "metadata": {
    "invocation_id": "inv_abc123",
    "workflow_name": "product_pipeline",
    "action_count": 3,
    "execution_mode": "parallel"
  },
  "results": [
    {
      "action_name": "extract_data",
      "status": "completed",
      "execution_time": 4.2,
      "record_count": 10,
      "tokens": 1500,
      "output_folder": "extract_data"
    }
  ],
  "elapsed_time": 12.5,
  "total_tokens": 4500
}
```

### Run History (`runs.json`)

**Path:** `artefact/runs.json`

`runs.json` is the cumulative catalog of past workflow executions surfaced by the documentation site. Every `agac run` writes to it twice via `RunTracker`:

- At start — a new execution entry is appended with `status: "running"`, `started_at`, and the action plan.
- At end — the entry is updated with the final `status` (`success` / `failed` / `paused`), `ended_at`, `duration_seconds`, and any `error_message`. Aggregate workflow metrics (`success_rate`, `avg_duration_seconds`) are recomputed in the same write.

`agac docs` reads `runs.json` to render the Run History view in the documentation site; if the file is missing when `agac docs` runs, an empty catalog is initialized so the page renders even before the first run completes.

```json
{
  "metadata": {"generated_at": "2026-03-24T10:00:00Z", "total_runs": 12},
  "executions": [
    {
      "id": "run_product_pipeline_a1b2c3d4",
      "workflow_id": "product_pipeline",
      "workflow_name": "product_pipeline",
      "status": "success",
      "started_at": "2026-03-24T10:00:00Z",
      "ended_at": "2026-03-24T10:02:30Z",
      "duration_seconds": 150.0,
      "actions_completed": 5,
      "actions_total": 5
    }
  ],
  "workflow_metrics": {
    "product_pipeline": {
      "total_runs": 8,
      "successful_runs": 7,
      "failed_runs": 1,
      "success_rate": 0.875,
      "avg_duration_seconds": 142.3
    }
  }
}
```

The most recent 100 executions are kept; older entries roll off as new runs land. The authoritative per-run summary is still `agent_io/logs/run_results.json` — that file captures the full per-action breakdown for the single run that produced it.

### Events Log (`events.json`)

**Path:** `agent_io/logs/events.json`

Complete telemetry of all system events in JSON Lines format (one event per line):

```jsonl
{"type": "WorkflowStartEvent", "timestamp": "2026-03-24T10:00:00Z", "workflow": "product_pipeline"}
{"type": "ActionStartEvent", "timestamp": "2026-03-24T10:00:01Z", "action": "extract_data"}
{"type": "LLMCallEvent", "timestamp": "2026-03-24T10:00:02Z", "vendor": "openai", "tokens": 500}
{"type": "ValidationPassEvent", "timestamp": "2026-03-24T10:00:03Z", "action": "extract_data"}
{"type": "ActionCompleteEvent", "timestamp": "2026-03-24T10:00:04Z", "action": "extract_data"}
```

#### Event Categories

| Category | Prefix | Examples |
|----------|--------|----------|
| Workflow | W | `WorkflowStartEvent`, `WorkflowCompleteEvent`, `WorkflowFailedEvent` |
| Action | A | `ActionStartEvent`, `ActionCompleteEvent`, `ActionSkipEvent`, `ActionFailedEvent` |
| Batch | B | `BatchSubmissionEvent`, `BatchStatusEvent` |
| LLM | L | `LLMCallEvent`, `TemplateRenderEvent` |
| Validation | V | `ValidationStartEvent`, `ValidationPassEvent`, `ValidationFailEvent` |
| Guard | G | `GuardEvaluationEvent`, `GuardPassEvent`, `GuardFailEvent` |
| Data I/O | FIO | `FileWriteStartedEvent`, `FileWriteCompleteEvent` |
| Cache | C | `CacheHitEvent`, `CacheMissEvent` |
| Recovery | R | `RetryExhaustedEvent` (R001), `RepromptValidationFailedEvent` (R002), `RecoveryErrorEvent` (R003), `RepromptRetryEvent` (R004), `RepromptRecoveredEvent` (R005) |

#### Recovery Events (R004/R005)

When reprompt validation retries, the event stream shows each attempt:

- **R004 `RepromptRetryEvent`** — fired before each retry attempt (not on the first attempt). Contains `attempt` (the upcoming 1-indexed attempt), `max_attempts`, and `error` (reason for failure).
- **R005 `RepromptRecoveredEvent`** — fired when validation passes after retries. Contains `attempt` (the 1-indexed attempt that succeeded) and `validation_name`.

A successful run that needed no retries produces zero R004/R005 events. This is by design — the events only fire when recovery actually occurs.

#### File Lifecycle

Both `events.json` and `errors.json` accumulate across runs by default. When `--fresh` is passed, both files are **deleted before the run starts** and recreated on the first event write. File watchers must handle the file being absent between deletion and first event.

### Errors Log (`errors.json`)

**Path:** `agent_io/logs/errors.json`

ERROR-level events only — a filtered subset of `events.json` for quick error diagnosis:

```jsonl
{"type": "ValidationFailEvent", "action": "extract_data", "error": "Required field 'name' missing"}
{"type": "ActionFailedEvent", "action": "generate_content", "error": "Rate limit exceeded"}
```

:::caution Monitoring change
`LLMJSONParseErrorEvent` (code L005) is now WARN level — it no longer appears in `errors.json`. Parse errors that reprompt recovers from are not true errors. Consumers monitoring parse failures must switch to `events.json` filtered by code `L005`.
:::

:::tip
When debugging, check `errors.json` first for a quick overview, then dive into `events.json` for the full trace around the failure timestamp.
:::

## Storage Backend (SQLite)

**Path:** `agent_io/store/{workflow_name}.db` (one database per workflow)

The SQLite database stores structured workflow data:

| Table | Purpose |
|-------|---------|
| `source_data` | Input records with deduplication by `source_guid` |
| `target_data` | Action outputs organized by `action_name` |
| `record_disposition` | Tracks the fate of individual records |

### Record Dispositions

| Disposition | Meaning |
|-------------|---------|
| `passthrough` | Record processed successfully |
| `skipped` | Intentionally skipped (guard with `on_false: skip`) |
| `filtered` | Removed from pipeline (guard with `on_false: filter`) |
| `exhausted` | Reprompt max attempts exceeded |
| `failed` | Processing failed |
| `unprocessed` | Not yet processed |

The `failed` and `exhausted` dispositions also store an `input_snapshot` column containing the JSON-serialized input record at the time of failure (truncated to 10KB). This enables post-mortem debugging even after batch recovery files have been cleaned up. Other disposition types do not populate this column.

### Querying the Database

```bash
sqlite3 agent_io/store/my_workflow.db

-- List all actions with output
SELECT DISTINCT action_name FROM target_data;

-- Count records per action
SELECT action_name, SUM(record_count) FROM target_data GROUP BY action_name;

-- Preview data from an action
SELECT data FROM target_data WHERE action_name = 'extract_data' LIMIT 1;

-- Check record dispositions
SELECT action_name, disposition, COUNT(*) FROM record_disposition GROUP BY action_name, disposition;
```

Or use the CLI preview command:

```bash
agac preview -w my_workflow
agac preview -w my_workflow -a extract_data -f json
agac preview -w my_workflow --stats
```

## Output Record Structure

Each output record contains tracking metadata:

```json
{
  "source_guid": "37812c37-80a2-596b-8747-8f93e7a34e7f",
  "content": {
    "product_name": "Smart Fitness Tracker",
    "category": "Wearable Technology"
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
| `lineage` | Chain of `node_id`s for provenance tracking |

## Documentation Catalog

**Path:** `artefact/catalog.json` (generated by `agac docs`)

The catalog is a snapshot of your entire project for the documentation site:

```bash
# Build and serve the documentation site
agac docs
```

The catalog contains: workflow definitions, action metadata, prompt templates, schema definitions, run history, and execution metrics. See [Documentation Site](../documentation-site) for the full browsable interface.

## Logs

```bash
# Set log level via environment variable
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow

# Or use the --debug flag
agac run -a my_workflow --debug
```

Log file location: `{project_root}/logs/agent_actions.log`

## Useful Commands

```bash
# Inspect run results
cat agent_io/logs/run_results.json | python3 -m json.tool

# Check for errors
cat agent_io/logs/errors.json

# Count events by type
cat agent_io/logs/events.json | python3 -c "
import sys, json, collections
counts = collections.Counter()
for line in sys.stdin:
    counts[json.loads(line)['type']] += 1
for k, v in counts.most_common():
    print(f'{v:4d} {k}')
"

# Preview action output via CLI
agac preview -w my_workflow -a extract_data

# Check workflow status
agac status -a my_workflow
```

## See Also

- **[Data I/O](../data-io/)** — Input/output directory structure and storage backends
- **[Data Lineage](../data-io/data-lineage)** — Tracking records across multi-action workflows
- **[Documentation Site](../documentation-site)** — Interactive project documentation
- **[Logging](../architecture/logging)** — Event system and log configuration
