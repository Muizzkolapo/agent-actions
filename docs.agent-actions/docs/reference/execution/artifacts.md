---
title: Artifacts & Run Tracking
sidebar_position: 3
---

# Artifacts & Run Tracking

Agent Actions makes artifacts for debugging, for audits and to resume interrupted runs. If you know this structure, you can examine what occurred during execution and find the cause of problems.

## Complete Directory Structure

```
project/
├── .agac/
│   └── batch_state/                    # What an offline-provider batch was submitted with,
│                                       # so the run that collects it can find it. Reclaimed
│                                       # when the batch registry stops naming the batch.
├── artefact/
│   ├── catalog.json                    # Project catalog (agac docs)
│   ├── runs.json                       # Workflow execution history (agac run + agac docs)
│   └── rendered_workflows/             # Partial rendered configs saved when preflight render fails
└── agent_workflow/
    └── my_workflow/
        └── agent_io/
            ├── .agent_status.json      # Per-action execution state
            ├── staging/                # Input data
            ├── store/
            │   └── {workflow_name}.db  # SQLite storage backend
            ├── logs/
            │   ├── .manifest.json      # Workflow execution manifest
            │   ├── run_results.json    # Summary metrics and timing
            │   ├── events.json         # Event telemetry of the current run (JSON Lines)
            │   ├── events.N.json       # Earlier runs; events.1.json is the newest
            │   ├── errors.json         # Error-level events of the current run (JSON Lines)
            │   └── errors.N.json       # Earlier runs' errors
            └── target/
                └── {action_name}/      # Output location named in run_results.json. Records live in
                                        # the store; `agac batch retrieve` writes results here
```

## Runtime Artifacts

### Workflow Manifest (`.manifest.json`)

**Path:** `agent_io/logs/.manifest.json`

The manifest holds the execution plan for the workflow run: the action order, the levels and the dependencies. The framework makes the manifest when the workflow starts. The framework sets the top-level `status` and `completed_at` when the run ends. During a run, the `status`, `started_at`, `completed_at`, `record_count` and `error` fields of each action stay at their start values. To read the state of each action, use `.agent_status.json`.

```json
{
  "schema_version": "1.0",
  "workflow_name": "product_pipeline",
  "workflow_run_id": "run_20260324_100000",
  "pid": 48213,
  "host_id": "9f2c1a77b4e03d58",
  "started_at": "2026-03-24T10:00:00.123456",
  "completed_at": "2026-03-24T10:02:30.654321",
  "status": "completed",
  "execution_order": ["extract_data", "generate_content"],
  "levels": [["extract_data"], ["generate_content"]],
  "actions": {
    "extract_data": {
      "index": 0,
      "level": 0,
      "status": "pending",
      "started_at": null,
      "completed_at": null,
      "output_dir": "extract_data",
      "dependencies": [],
      "record_count": null,
      "error": null
    }
  }
}
```

`pid` and `host_id` identify the process that owns the run. A process that is killed
immediately never records a terminal status. Thus readers use `pid` and `host_id` to find if
that process still exists. If it does not exist, readers report its active actions as `interrupted`.
They do not show these actions as running forever. `host_id` is a hash of the
hostname, not the hostname, because `agac docs` publishes this file.
A reader that finds no `pid`, or a `host_id` that is not its own, makes no
decision.

The VS Code Workflow Navigator reads this file. It uses the data to show the sidebar tree view and the DAG (directed acyclic graph) view.

### Action Status (`.agent_status.json`)

**Path:** `agent_io/.agent_status.json`

This file keeps the execution state of each action, so that a run can resume:

```json
{
  "extract_data": {"status": "completed", "record_limit": 2, "file_limit": null,
                   "records_processed": 2, "truncated": true},
  "generate_content": {"status": "completed", "record_limit": null, "file_limit": null,
                       "records_processed": 40, "truncated": false},
  "validate_output": {"status": "pending"}
}
```

A completed action also stores the conditions that it ran under. Thus the next run can tell an
action that is really finished from an action that stopped before its end. `record_limit` and
`file_limit` are the limits that were **in force**, not the limits that the config
asks for. The limit in force comes from the workflow config, the flag or the environment variable, whichever won.
With them are `records_processed` and `truncated`. These keys say what
the run actually did, not what the run was asked to do. The action also stores `model_name`,
`model_vendor` and a `config_hash` over the prompt, the schema and the guard.

The data that the action reads has its own digests: `context_scope_hash` over its `context_scope` (observe,
passthrough, drop and seed) and `dependencies_hash` over its `dependencies`. How the action
is asked also has a digest: `generation_hash` over the generation settings that an LLM action sends
(`temperature`, `max_tokens`, `top_p`, `stop`, `frequency_penalty`, `presence_penalty` and `vendor_params`).
`generation_hash` is empty for a tool or hitl action, because such an action sends no generation settings. The code that the action runs also has a digest:
`udf_source_hash`. It covers the files that its tool (`impl`) and its UDF guard were loaded from, as
they were when the run loaded them. The model and these four digests are outside `config_hash` on purpose. Thus, when the framework added them, they could not change
all stored digests at the same time. They also could not name each completed action as edited after an upgrade.

A change to one of these items counts as an edit to a completed action:

- Its prompt, its schema or its guard
- Its model
- Its context scope
- Its dependencies
- Its generation settings
- The code of its tool or of its UDF guard

An answer is the output that an action gives for a record. An edit re-runs nothing. The action keeps its
answers, and each action that reads it also keeps its answers. Each run names the edit, for example
`recap was edited since it completed (context scope): its answers stand, and only records
it has not answered use the edit. Run again with --rerun recap to answer every record under
the edit`, until `agac run --rerun recap` answers the action and its readers under the new config.
See [When you edit the workflow](../cli/run#when-you-edit-the-workflow).

If you reorder or repeat the entries of an `observe`, `passthrough` or `drop` list, that change is not
an edit. If you reorder `dependencies`, that change is an edit, because a fan-in merges its inputs in that order. The framework
tracks a tool or a guard by its whole file. Thus an edit anywhere in that file names each
action whose tool or guard that file defines. The framework does not track a module that the file imports, or
the contents of a seed data file. Thus, after you change one of these, use `--rerun` or `--fresh`. A stamp written before a digest existed holds no value
for that digest. Thus the framework does not name an edit that the digest would catch until the action completes again.

A changed `record_limit` re-runs the action only when the old limit could have held
back some records. An untruncated run processed all of the records that there were. Thus a limit at
or above that count would also drop nothing, and the action stays complete. A
run that did truncate gives no guarantee for any limit. Some stamps cannot say what the run processed:

- A stamp written before these counts existed.
- A stamp written by a run that never sliced.
- A stamp written by a run that lost an input file to an error. The run never counted the records that it never got to.

These stamps keep the coarse rule, and the action re-runs. `file_limit` has no count to reason from, and it always
uses the coarse rule. Any change to it re-runs the action. This includes a change to a
value larger than the number of files. A limit that changes re-runs the action and each
action that reads it.

A first-stage action (an action with no `dependencies`) also stores `staged_input`. This key holds the
relative path, the size and the modification time of each input file that the action read. When a later
run finds a file that was added, removed or changed, the run logs which file. It then sets that action and
each completed action that reads it back to `pending`. These actions keep their answers. They run
again and answer only the records that the change added or changed. (A changed record has a
new `source_guid`, so it is a new record.)

A record that no staged file holds any more
loses its rows, its dispositions and its checkpoints at that action. It also loses them at each action
that reads it. This occurs after a walk has read all of the staged files. The prompt traces of the record stay. The framework
forgets nothing under a file limit, after a file failed to read, or during `agac retry`.
`--rerun` answers each record again. Staging that did not change still skips. A stamp written before this key existed holds no value. The framework does
not change that stamp until the action completes again.

When an action starts work, it also records the config that the work is answered under.
This is `answered_under`, which holds the same `config_hash`, `model_name`, `model_vendor`,
`context_scope_hash`, `dependencies_hash`, `generation_hash` and `udf_source_hash`. A run can stop partway
through an action because it is killed, interrupted or stopped by an error. That run leaves the records that it
finished, and the next run keeps them. Between the two runs, the prompt, schema, guard, model, context scope,
dependencies, generation settings or tool or guard code can be edited. These are the same edits as for a completed action, above.
After such an edit, the next run names the edit and answers only the remaining records under it.

If the action kept any
answer, its stamps stay at the config that those
answers were given under (`kept_answers_under` in the status file). A batch that was sent and not yet collected counts as a kept answer. Thus each later run names the edit until
`--rerun` answers each record under it. An action that may hold answers from more than one
config has a mark (`answers_under_more_than_one_config`). Each run reports the mark, also after
the edit is undone. The framework does not see a change to a module that a tool imports, or to the contents of
a seed data file. Thus, after such a change, run `agac run --rerun <action>` or `--fresh` to answer
all records again.

The framework does not keep the verdict of a guard. The run that resumes the action gives each
record to the guard again. Thus a record that the guard code now skips is skipped, and a record that it now
passes is answered. The exception is a record of a batch action whose batch was out, or
finished and not yet collected, when the run stopped. That record keeps the answer that the batch
brings. The reason is that the guard judged the record when the batch was sent, and the collection of the batch judges
nothing.

A record can be finished in a file that the stopped run did not write yet. If an earlier run stored that file, the record is
answered again. The reason is that the stored row is older than
its answer. The store can fail to write a file, on a full disk or a database error. That failure also stops the action
in this way. The run ends `failed`, and the next run writes that file. Online,
the run first writes the other files of the action. After a `--rerun`, each run that fails
to store the file asks for its records again, as above. A batch collect pass stops at the
file. A later run collects that file and the files after it, and it does not send any of them
again.

For the records that it does not name, an `agac retry` instead records the config that those records were answered under.
That config is the stamp of the last completion of the action. If the action
never completed, it is the config that the last run recorded. Thus a retry, stopped or finished, keeps the edit named on the next run.
Each prompt trace row records the config that its record was answered under. This includes the retried
records.

A reset leaves the data that the action stored in place. The re-run replaces that data file by file.
Sometimes every record of the re-run fails in a file, for one of these causes:

- The answers of the model do not parse.
- A tool of record granularity raises an error on each record, or answers each record with output that its schema refuses.
- A tool of file granularity raises an error on the file.

The framework stores such a file with those
failures, in the same way as a file
in which only some records fail. Thus the action and its readers keep no row answered
before the reset, and `agac retry` asks for those records again. Outside a reset, a run that
answers nothing in a file and fails some of it leaves the data that the file held.

Staged input is the source of truth for the data that an action holds. An action can be reset after
its input was removed, by an edit applied with `--rerun` or by a limit given on the command
line. Such an action finds no input file and is skipped. The framework deletes its stored output and
the stored output of its readers. To rebuild them, restore the input and run again.

A reset can occur after only
some of the input files of the action were removed. The action then deletes the data that it stored for those files, after it
has read each file that is still there. Its readers do the same. A batch action does this when
it submits. A file that failed to process keeps its output. These runs delete nothing:

- A run that a file limit stopped before its last file.
- A run that could not list part of its input, or could not read the data that its upstream action stored.
- An `agac retry` that repairs the records that it names.

A retry that names no record, for example a retry that resumes a halted action, runs its actions
in full. It deletes data in the same way as a run.

A version merge sees each file that its versions hold,
whatever its file limit. Thus, before it runs, it deletes the data that it stored for a file that no version
holds. This also occurs under `agac retry`. To rebuild
them, restore the files and run with `--fresh`. If each version holds a file empty, the merge and its readers hold
nothing for that file. A merge stores only its answers. `agac retry`, or a run
resumed after it stopped, keeps them for each record that it does not ask again.

| Status | Description |
|--------|-------------|
| `pending` | The action did not run yet |
| `running` | The action runs now |
| `completed` | The action finished successfully |
| `completed_with_failures` | The action finished, but one or more records failed or were exhausted |
| `failed` | The action stopped with an error |
| `interrupted` | The run was killed while this action ran, or the process that owned it no longer exists |
| `skipped` | The action was skipped. The cause is one of these: a guard, a failed or skipped dependency (or version source), or no input file. The skip also occurs when all version sources come back empty. If the input of a skipped action holds nothing, the action also holds nothing. The framework deletes the rows that the action stored before. If its input still holds rows (a failed run keeps its answers), the action keeps its own rows |
| `batch_submitted` | The batch job was submitted, and the framework waits for the results |
| `checking_batch` | The run checks if a submitted batch has finished |

When you run a workflow again, the run skips completed actions and resumes from the failure point. It keeps the records that a stopped action finished, edited or not. A completed first-stage action whose staged input files changed runs again, with all of its readers. It answers only the records that the change added or changed.

### Run Results (`run_results.json`)

**Path:** `agent_io/logs/run_results.json`

This file is a summary of the workflow execution, with the metrics of each action:

```json
{
  "metadata": {
    "invocation_id": "run_product_pipeline_89381a13",
    "workflow_name": "product_pipeline",
    "action_count": 3,
    "execution_mode": "parallel",
    "started_at": "2026-03-24T10:00:00.123456+00:00",
    "completed_at": "2026-03-24T10:00:12.623456+00:00",
    "elapsed_time": 12.5,
    "status": "success"
  },
  "results": [
    {
      "unique_id": "product_pipeline.extract_data",
      "action_name": "extract_data",
      "action_index": 0,
      "status": "success",
      "execution_time": 4.2,
      "output_folder": "/path/to/agent_workflow/product_pipeline/agent_io/target/extract_data",
      "record_count": 10,
      "tokens": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
      "error_message": null,
      "skip_reason": null,
      "empty_output_records": 0,
      "timing": {
        "started_at": "2026-03-24T10:00:00.200000+00:00",
        "completed_at": "2026-03-24T10:00:04.400000+00:00"
      }
    }
  ],
  "elapsed_time": 12.5,
  "tokens": {"prompt_tokens": 3000, "completion_tokens": 1500, "total_tokens": 4500}
}
```

An action that has a guard also carries a `guard_stats` object. The object holds the `condition`, the counts `passed` and `filtered`, and `on_false`.

### Run History (`runs.json`)

**Path:** `artefact/runs.json`

`runs.json` is the cumulative catalog of past workflow executions. The documentation site shows this catalog. Each `agac run` writes to it two times, through `RunTracker`:

- At the start — `RunTracker` puts a new execution entry at the front of `executions`, with `status: "running"`, `started_at` and `total_actions`. Each action adds its own entry when it starts and when it finishes.
- At the end — `RunTracker` updates the entry with the final `status` (`SUCCESS` / `FAILED` / `PAUSED`), `ended_at`, `duration_seconds` and any `error_message`. The same write calculates the aggregate workflow metrics (`success_rate`, `avg_duration_seconds`) again.

`agac docs` reads `runs.json` to render the Run History view in the documentation site. If the file is missing when `agac docs` runs, `agac docs` makes an empty catalog. Thus the page renders even before the first run completes.

```json
{
  "metadata": {"generated_at": "2026-03-24T10:00:00+00:00", "total_runs": 12, "schema_version": "1.0"},
  "executions": [
    {
      "id": "run_product_pipeline_a1b2c3d4",
      "workflow_id": "product_pipeline",
      "workflow_name": "product_pipeline",
      "status": "SUCCESS",
      "started_at": "2026-03-24T10:00:00+00:00",
      "ended_at": "2026-03-24T10:02:30+00:00",
      "duration_seconds": 150.0,
      "total_actions": 5,
      "successful_actions": 5,
      "failed_actions": 0,
      "skipped_actions": 0,
      "total_tokens": 0,
      "error_message": null,
      "actions": {
        "extract_data": {
          "status": "success",
          "started_at": "2026-03-24T10:00:01+00:00",
          "ended_at": "2026-03-24T10:01:15+00:00",
          "duration_seconds": 74.0,
          "type": "tool",
          "impl": "extract_data"
        }
      }
    }
  ],
  "workflow_metrics": {
    "product_pipeline": {
      "total_runs": 8,
      "successful_runs": 7,
      "failed_runs": 1,
      "total_tokens": 0,
      "success_rate": 0.875,
      "avg_duration_seconds": 142.3
    }
  }
}
```

The file keeps the 100 most recent executions. When new runs occur, the framework removes the oldest entries. The authoritative summary of each run is still `agent_io/logs/run_results.json`. That file holds the full data of each action for the one run that made it.

### Events Log (`events.json`)

**Path:** `agent_io/logs/events.json`

This file holds the telemetry of the current workflow run in JSON Lines format (one event on each line). Earlier runs are in `events.1.json` (newest) to `events.N.json`:

```jsonl
{"event_type": "WorkflowStartEvent", "code": "W001", "level": "info", "category": "workflow", "message": "Running workflow product_pipeline (4 actions)", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:00Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"workflow_name": "product_pipeline", "action_count": 4, "execution_mode": "parallel"}}
{"event_type": "StepStartEvent", "code": "W004", "level": "info", "category": "workflow", "message": "Step 2/3: extract_data", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:01Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"step_index": 1, "total_steps": 3, "actions": ["extract_data"], "pending": ["extract_data"]}}
{"event_type": "ActionStartEvent", "code": "A001", "level": "info", "category": "action", "message": "2/4 START extract_data", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:01Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"action_name": "extract_data", "action_index": 1, "total_actions": 4, "action_type": "llm", "input_path": "", "mode": "online"}}
{"event_type": "LLMRequestEvent", "code": "L001", "level": "debug", "category": "llm", "message": "LLM request to openai/gpt-4o (412 prompt tokens)", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:02Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"provider": "openai", "model": "gpt-4o", "action_name": "extract_data", "prompt_tokens": 412, "request_id": ""}}
{"event_type": "LLMResponseEvent", "code": "L002", "level": "info", "category": "llm", "message": "LLM response: 500 tokens in 1840ms", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:03Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"provider": "openai", "model": "gpt-4o", "action_name": "extract_data", "prompt_tokens": 412, "completion_tokens": 88, "total_tokens": 500, "latency_ms": 1840.0, "request_id": ""}}
{"event_type": "ActionCompleteEvent", "code": "A002", "level": "info", "category": "action", "message": "2/4 OK extract_data in 2.10s", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:04Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"action_name": "extract_data", "action_index": 1, "total_actions": 4, "execution_time": 2.1, "output_path": "", "record_count": 23, "tokens": {}, "mode": "online", "model_vendor": "openai", "model_name": "gpt-4o", "kind": "llm", "guard_skipped": 0, "checks_failed": 0}}
{"event_type": "StepCompleteEvent", "code": "W005", "level": "info", "category": "workflow", "message": "Step 2/3 complete in 2.10s", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:04Z", "correlation_id": null, "invocation_id": null, "thread_id": null}, "data": {"step_index": 1, "total_steps": 3, "elapsed_time": 2.1, "completed": 1, "partial": 0, "skipped": 0, "failed": 0, "unfinished": 0, "batch_pending": []}}
```

Each line carries the same envelope. A parser should use `event_type` or `code` as the key.
The payload is always under `data`, and the timestamp is always under `meta`. They are never at the top
level.

| Key | What it holds |
|-----|---------------|
| `event_type` | The class name, for example `ActionStartEvent` |
| `code` | A stable short code, for example `A001`. To match events, use the code, not the class name |
| `level` | `debug`, `info`, `warn` or `error` |
| `category` | A coarse group, for example `action`, `llm`, `data_processing` |
| `message` | The rendered line that a person can read |
| `diagnostic` | `true` when the line describes framework internals. The console hides these lines unless the run is verbose. The framework always writes them here |
| `meta` | `timestamp`, `correlation_id`, `invocation_id`, `thread_id`, and the context of the run. The context is `workflow_name` and, on an event that occurs while an action runs, the `action_name` and `action_index` of that action. The actions of one step run at the same time, and each event names the action that caused it |
| `data` | The fields of the event. The shape is different for each `event_type` |

#### Event Codes

A code is a prefix and an ordinal number. The prefix groups related events. The prefix is not always the
same string as `category`.

| Prefix | Category | Examples |
|--------|----------|----------|
| W | `workflow` | `WorkflowStartEvent` (W001), `WorkflowCompleteEvent` (W002), `WorkflowFailedEvent` (W003), `StepStartEvent` (W004), `StepCompleteEvent` (W005) |
| A | `action` | `ActionStartEvent` (A001), `ActionCompleteEvent` (A002), `ActionSkipEvent` (A003), `ActionFailedEvent` (A004), `ActionCachedEvent` (A005) |
| L | `llm` | `LLMRequestEvent` (L001), `LLMResponseEvent` (L002), `LLMErrorEvent` (L003), `RateLimitEvent` (L004), `LLMJSONParseErrorEvent` (L005) |
| T | `template` | `TemplateRenderingFailedEvent` (T001) |
| B | `batch` | `BatchSubmittedEvent` (B001), `BatchCompleteEvent` (B003), `BatchStatusEvent` (B008), `BatchSubmissionFailedEvent` (B009) |
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
| FIO | `file_io` | `SourceDataSavingEvent` (FIO001), `SchemaLoadedEvent` (FIO004), `FileWriteStartedEvent` (FIO005), `FileWriteCompleteEvent` (FIO006), `FileWriteFailedEvent` (FIO007), `LogFileCapReachedEvent` (FIO008) |
| C | `cache` | `CacheHitEvent` (C001), `CacheMissEvent` (C002), `CacheInvalidationEvent` (C003) |
| F | `configuration` | `ConfigLoadStartEvent` (F001), `ConfigLoadEvent` (F002) |
| I | `initialization` | `CLIInitStartEvent` (I001), `WorkflowInitializationStartEvent` (I008), `ProjectInitializedEvent` (I013) |
| P | `plugin` | `UDFDiscoveryStartEvent` (P001), `UDFDiscoveryCompleteEvent` (P003) |

#### Recovery Events

- **R001 `RetryExhaustedEvent`** — occurs when the transport retry stops. It contains the operation, the attempt count and the last error.
- **RC004 `ExhaustedRecordEvent`** — occurs when a record is exhausted after recovery failed. It contains `action_name`, `record_index`, `source_guid` and `reason`.

A run whose records all succeed at the first attempt makes neither event. This is by design. The events occur only when recovery actually occurs.

#### File Lifecycle

`events.json` and `errors.json` hold one workflow run. When `agac run` or `agac retry` starts, each file moves one position back. `events.json` becomes `events.1.json`, `events.1.json` becomes `events.2.json`, and the sequence continues. The framework keeps the last 5 runs. To keep a different number, set `AGENT_ACTIONS_LOG_RETAIN_RUNS` (an integer of 1 or more). Other commands that log into the workflow, for example `agac batch`, add to the file of the current run. They do not rotate it.

When a run file gets to 50 MB, it stops taking DEBUG events. At that time, it records `LogFileCapReachedEvent` (FIO008, WARN) one time. The framework always writes INFO, WARN and ERROR events. To change the cap, set `AGENT_ACTIONS_LOG_MAX_BYTES`. For no cap, set it to `0`.

When you give `--fresh`, the framework **deletes these files before the run starts**. It deletes each `events*.json` and `errors*.json` file in the `agent_io/logs/` folder of the workflow. The framework makes `events.json` again on the first event write. File watchers must accept that the file is absent between the rotation or deletion and the first event.

### Errors Log (`errors.json`)

**Path:** `agent_io/logs/errors.json`

This file holds only ERROR-level events. It is a filtered subset of `events.json`, so that you can find errors quickly. Each line has the same envelope as `events.json`:

```jsonl
{"event_type": "GuardEvaluationErrorEvent", "code": "G002", "level": "error", "category": "guard", "message": "Guard evaluation failed: Guard condition references field 'src.descx' which does not exist in the data. Available top-level fields: source, src, workflow", "diagnostic": false, "meta": {"timestamp": "2026-03-24T10:00:03+00:00", "correlation_id": "d96faa45"}, "data": {"guard_clause": "src.descx == 'a'", "error": "Guard condition references field 'src.descx' which does not exist in the data. Available top-level fields: source, src, workflow"}}
```

:::warning[CAUTION]
`LLMJSONParseErrorEvent` (code L005) is now WARN level. It no longer appears in `errors.json`. A parse error that the repair loop recovers from is not a true error. Consumers that monitor parse failures must use `events.json`, filtered by code `L005`.
:::

To debug, examine `errors.json` first for a quick overview. Then examine `events.json` for the full trace near the failure timestamp.

## Storage Backend (SQLite)

**Path:** `agent_io/store/{workflow_name}.db` (one database per workflow)

The SQLite database stores structured workflow data:

| Table | Purpose |
|-------|---------|
| `source_data` | Input records, with deduplication by `source_guid` |
| `target_data` | Action outputs, in groups by `action_name` |
| `record_disposition` | What occurred to each record |

### Record Dispositions

| Disposition | Meaning |
|-------------|---------|
| `success` | The record was processed successfully |
| `passthrough` | The answer was empty. The framework keeps the record as a tombstone (`on_empty: skip`) |
| `skipped` | The framework excluded the record from this action before its guard ran, or the full action was skipped |
| `deferred` | The record was sent to a batch provider, and the framework waits for its result |
| `filtered` | The framework removed the record from this action and from each downstream action (guard with `on_false: filter`) |
| `exhausted` | Recovery stopped. All retry attempts or `expect` iterations were used |
| `failed` | Processing failed |
| `unprocessed` | The record has no answer. An upstream failure cascaded, or a guard with `on_false: skip` skipped the record. The next run gives the record to the guard again |

The `failed` and `exhausted` dispositions also store an `input_snapshot` column. This column holds the input record, serialized as JSON, at the time of the failure. The framework stores an input over 10 KB as a truncation marker that holds its first 8,192 characters. Thus you can debug after the failure, even after the framework removed the batch recovery files. Other disposition types do not write this column.

### Querying the Database

```bash
sqlite3 agent_io/store/my_workflow.db

-- List all actions with output
SELECT DISTINCT action_name FROM target_data;

-- Count records per action
SELECT action_name, SUM(record_count) FROM target_data GROUP BY action_name;

-- Check record dispositions
SELECT action_name, disposition, COUNT(*) FROM record_disposition GROUP BY action_name, disposition;
```

The `data` column is compressed in the store. To print the records of an action, use `agac records -w my_workflow -a extract_data` (see [records](../cli/records)). You can also use the CLI preview command:

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
    "extract_data": {
      "product_name": "Smart Fitness Tracker",
      "category": "Wearable Technology"
    }
  },
  "target_id": "dd45e6ef-63d6-45f6-8759-5df33c9a84a2",
  "node_id": "extract_data_86a1e066-9522-4e0e-a3db-e83c7e38ab8c",
  "lineage": ["extract_data_86a1e066-9522-4e0e-a3db-e83c7e38ab8c"],
  "parent_target_id": "0ef93d35-4f64-4cf3-9cfc-272e7311a539",
  "root_target_id": "0ef93d35-4f64-4cf3-9cfc-272e7311a539",
  "metadata": {"model": "dp_src", "provider": "tool"}
}
```

A record also carries lifecycle fields, for example `_state` and `_state_history`.

| Field | Description |
|-------|-------------|
| `source_guid` | The link to the original input record |
| `content` | The action output, validated against the schema, under the name of the action |
| `target_id` | The unique identifier of this output |
| `node_id` | The identifier of the action execution |
| `lineage` | The chain of `node_id`s that shows the origin of the record |

## Documentation Catalog

**Path:** `artefact/catalog.json` (generated by `agac docs`)

The catalog is a snapshot of your full project for the documentation site:

```bash
# Build and serve the documentation site
agac docs
```

The catalog contains these items:

- Workflow definitions
- Action metadata
- Prompt templates
- Schema definitions
- Run history
- Execution metrics
- A bounded tail of the event stream. All of the logs that the project wrote share this tail.

For the full interface that you can browse, see [Documentation Site](../documentation-site).

## Logs

```bash
# Set log level via environment variable
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow

# Or use the --debug flag, which goes before the command
agac --debug run -a my_workflow
```

The framework writes the events of each run to `agent_io/logs/events.json` and `errors.json` in the workflow folder (see above).

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
    counts[json.loads(line)['event_type']] += 1
for k, v in counts.most_common():
    print(f'{v:4d} {k}')
"

# Preview action output via CLI
agac preview -w my_workflow -a extract_data

# Check workflow status
agac status -a my_workflow
```

## See Also

- **[Data I/O](../data-io/)** — The input and output directory structure, and the storage backends
- **[Data Lineage](../data-io/data-lineage)** — Track records through workflows that have many actions
- **[Documentation Site](../documentation-site)** — Interactive project documentation
- **[Logging](../architecture/logging)** — The event system and the log configuration
