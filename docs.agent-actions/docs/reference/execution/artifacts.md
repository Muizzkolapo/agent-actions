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
  "pid": 48213,
  "host_id": "9f2c1a77b4e03d58",
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

`pid` and `host_id` identify the process that owns the run. A process killed
outright never records a terminal status, so readers use them to check whether
that process still exists and report its in-flight actions as `interrupted`
rather than showing them as running forever. `host_id` is a hash of the
hostname, not the hostname, because this file is published by `agac docs`.
A reader that finds no `pid`, or a `host_id` that is not its own, makes no
judgement at all.

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
| `interrupted` | The run was killed while this action was executing, or the process that owned it no longer exists |
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
{"event_type": "WorkflowStartEvent", "code": "W001", "level": "info", "category": "workflow", "message": "Running workflow product_pipeline (4 actions)", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:00Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"workflow_name": "product_pipeline", "action_count": 4, "execution_mode": "parallel"}}
{"event_type": "ActionStartEvent", "code": "A001", "level": "info", "category": "action", "message": "2/4 START extract_data", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:01Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"action_name": "extract_data", "action_index": 1, "total_actions": 4, "action_type": "llm", "input_path": "", "mode": "online"}}
{"event_type": "LLMRequestEvent", "code": "L001", "level": "debug", "category": "llm", "message": "LLM request to openai/gpt-4o (412 prompt tokens)", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:02Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"provider": "openai", "model": "gpt-4o", "action_name": "extract_data", "prompt_tokens": 412, "request_id": ""}}
{"event_type": "LLMResponseEvent", "code": "L002", "level": "debug", "category": "llm", "message": "LLM response: 500 tokens in 1840ms", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:03Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"provider": "openai", "model": "gpt-4o", "action_name": "extract_data", "prompt_tokens": 412, "completion_tokens": 88, "total_tokens": 500, "latency_ms": 1840.0, "request_id": ""}}
{"event_type": "ActionCompleteEvent", "code": "A002", "level": "info", "category": "action", "message": "2/4 OK extract_data in 2.10s", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:04Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"action_name": "extract_data", "action_index": 1, "total_actions": 4, "execution_time": 2.1, "output_path": "", "record_count": 23, "tokens": {}, "mode": "online"}}
```

Every line carries the same envelope. A parser should key on `event_type` or `code`;
the payload is always under `data`, and the timestamp under `meta`, never at the top
level.

| Key | What it holds |
|-----|---------------|
| `event_type` | The class name, e.g. `ActionStartEvent` |
| `code` | Stable short code, e.g. `A001` — prefer this over the class name for matching |
| `level` | `debug`, `info`, `warn` or `error` |
| `category` | Coarse grouping, e.g. `action`, `llm`, `data_processing` |
| `message` | Rendered human-readable line |
| `diagnostic` | `true` when the line describes framework internals. The console hides these unless the run is verbose; they are always written here |
| `meta` | `timestamp`, `correlation_id`, `invocation_id`, `thread_id` |
| `data` | Per-event fields; the shape differs by `event_type` |

#### Event Codes

Codes are prefix + ordinal. The prefix groups related events; it is not always the
same string as `category`.

| Prefix | Category | Examples |
|--------|----------|----------|
| W | `workflow` | `WorkflowStartEvent` (W001), `WorkflowCompleteEvent` (W002), `WorkflowFailedEvent` (W003) |
| A | `action` | `ActionStartEvent` (A001), `ActionCompleteEvent` (A002), `ActionSkipEvent` (A003), `ActionFailedEvent` (A004), `ActionCachedEvent` (A005) |
| L | `llm` | `LLMRequestEvent` (L001), `LLMResponseEvent` (L002), `LLMErrorEvent` (L003), `RateLimitEvent` (L004), `LLMJSONParseErrorEvent` (L005) |
| T | `template` | `TemplateRenderingFailedEvent` (T001) |
| B | `batch` | `BatchSubmittedEvent` (B001), `BatchProgressEvent` (B002), `BatchCompleteEvent` (B003), `BatchStatusEvent` (B008), `BatchSubmissionFailedEvent` (B009) |
| BP | `data_processing` | `BatchProcessingStartedEvent` (BP001), `BatchProcessingProgressEvent` (BP002), `BatchDataProcessingCompleteEvent` (BP003) |
| RP | `data_processing` | `RecordProcessingStartedEvent` (RP001), `RecordFilteredEvent` (RP002), `RecordTransformedEvent` (RP003), `RecordEmptyOutputEvent` (RP005) |
| DT | `data_processing` | `EnrichmentPipelineStartedEvent` (DT001), `EnricherExecutedEvent` (DT002), `EnrichmentPipelineCompleteEvent` (DT003) |
| RC | `data_processing` | `ResultCollectionStartedEvent` (RC001), `ResultCollectedEvent` (RC002), `ResultCollectionCompleteEvent` (RC003), `ExhaustedRecordEvent` (RC004) |
| CX | `data` | `ContextNamespaceLoadedEvent` (CX001), `ContextFieldSkippedEvent` (CX002), `ContextScopeAppliedEvent` (CX003), `ContextFieldNotFoundEvent` (CX006) |
| D | `data` | `DataParsingErrorEvent` (D001), `DataLoadingErrorEvent` (D002) |
| V | `validation` | `ValidationStartEvent` (V001), `ValidationCompleteEvent` (V002), `ValidationErrorEvent` (V003), `ValidationWarningEvent` (V004) |
| DV | `validation` | `DataValidationStartedEvent` (DV001), `DataValidationPassedEvent` (DV002), `DataValidationFailedEvent` (DV003) |
| G | `guard` | `GuardEvaluationTimeoutEvent` (G001), `GuardEvaluationErrorEvent` (G002) |
| R | `recovery` | `RetryExhaustedEvent` (R001) |
| SO | `schema` | `SchemaConstructionStartedEvent` (SO001), `SchemaConstructionCompleteEvent` (SO002) |
| FIO | `file_io` | `SourceDataSavingEvent` (FIO001), `SchemaLoadedEvent` (FIO004), `FileWriteStartedEvent` (FIO005), `FileWriteCompleteEvent` (FIO006) |
| C | `cache` | `CacheHitEvent` (C001), `CacheMissEvent` (C002), `CacheInvalidationEvent` (C003) |
| F | `configuration` | `ConfigLoadStartEvent` (F001), `ConfigLoadEvent` (F002) |
| I | `initialization` | `CLIInitStartEvent` (I001), `WorkflowInitializationStartEvent` (I008), `ProjectInitializedEvent` (I013) |
| P | `plugin` | `UDFDiscoveryStartEvent` (P001), `UDFDiscoveryCompleteEvent` (P003) |

#### Recovery Events

- **R001 `RetryExhaustedEvent`** — fired when transport retry gives up. Contains the operation, the attempt count and the last error.
- **RC004 `ExhaustedRecordEvent`** — fired when a record is exhausted after recovery failed. Contains `action_name`, `record_index`, `source_guid` and `reason`.

A run whose records all succeed first time produces neither. This is by design — the events only fire when recovery actually occurs.

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
`LLMJSONParseErrorEvent` (code L005) is now WARN level — it no longer appears in `errors.json`. Parse errors the repair loop recovers from are not true errors. Consumers monitoring parse failures must switch to `events.json` filtered by code `L005`.
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
| `exhausted` | Recovery gave up — retry attempts or `expect` iterations spent |
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
