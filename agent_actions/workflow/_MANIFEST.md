# Workflow Manifest

**[> Architecture Guide (ARCHITECTURE.md)](ARCHITECTURE.md)** — full execution flow, status lifecycle, config pipeline, batch lifecycle, caveats.

## Overview

Workflow orchestration, execution, schema services, and workspace metadata for
Agent Actions.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [managers](managers/_MANIFEST.md) | Lifecycle/state managers, artifact helpers, and batching logic. |
| [parallel](parallel/_MANIFEST.md) | Parallel execution/dependency helpers used during workflow runs. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `config_pipeline.py` | Module | Config loading and UDF discovery extracted from coordinator. Schema validation is handled by `WorkflowSchemaService` via static analysis. | `config` |
| `coordinator.py` | Module | Orchestration-only facade: delegates config, services, and events to extracted modules. Stores `schema_service` for reuse by callers. Raises `ConfigurationError` when `storage_backend` is `None` after service init. `set_retried_records()` names the records a run is repairing. A repair processes those and no others: the selection is applied above the source save, the context scope and the guard, and the file walk resolves to the files holding them, which no file limit then cuts short. Record limits still admit them on top of their own N at actions where the limit runs first. The startup reset (`_reset_retryable_actions`) keeps what an action stopped partway (killed, interrupted, or failed) finished only while its config matches the one its run recorded as it started; edited since, it and what reads it are reset as a changed completed action is and lose their prompt traces, and state from before that record is reset by its status. | `workflow` |
| `execution_events.py` | Module | `WorkflowEventLogger` class encapsulating all workflow/action event firing, plus `fire_step_start`/`fire_step_complete` shared by the sequential and parallel run paths. | `logging`, `events` |
| `executor.py` | Module | Handles running actions (LLM/tool/HITL) and interfacing with processors. Stamps an action with the record and file limits in force, how many records the run actually processed and whether the record limit cut any (`records_processed`/`truncated`), the model and a config digest, so a run shortened from the command line or the environment is not later served as a finished one, while a record limit too large to have dropped anything leaves the action completed instead of clearing its dispositions and re-running it. A stamp that cannot say keeps the older, coarser behaviour, as does the file axis, which has no count to reason from. The stamp is written when a batch is submitted as well as when an action completes, because the run that walks the files is the one that can describe them and a later run collects them; that collecting run keeps what the submission wrote. A run that is only repairing records neither stamps nor compares any of it, unless the action is completing for the first time — there is no earlier stamp to preserve then, and recording nothing is indistinguishable from a full uncapped run, which serves the action as finished on the records the repair named. The slice counts stay unrecorded under a repair even then, because they come from the limit's own slice and a repair narrows that slice again before anything is written. When a completed action is put back to pending because its config, model or limits changed or its stored output is gone, every action that reads its output is reset with it, whatever state it was left in and whether it reads it as a dependency or only names it in its context scope: what it holds was computed from what is about to be replaced. Dispositions, checkpoint records and batch state are cleared, and a batch still out is given up with a warning. The stores are cleared first and every status is written last in one write, so a run killed part-way does it again. Starting an action's work records beside the status what it is answered under (`answered_under`: config digest and model), for the startup reset to compare; `reopen_with_readers` is the reset both use. A run that is repairing records acts on no comparison (it warns when it meets an edited action), resets no reader and keeps the config stamp it found, as it keeps the limits, and records that stamp as what its work is answered under, so the next plain run still finds an edit. An action that never completed has no stamp to keep: there the repair records, and on completing stamps, the `answered_under` its last run recorded. A skip never rewrites stored output, so a skipped action whose input holds nothing has its rows deleted: one skipped by the circuit breaker when any upstream the breaker judges (its concrete dependencies and version sources; a version base named in `dependencies` is not one) holds no rows, and one skipped because every version source came back empty, always. A source named only in the context scope does not count: the breaker runs past it, so rows built while it held nothing are not stale for it (#1228 tracks giving both one notion of what an action reads). What called those rows done (dispositions, checkpoint records, batch state) goes first, since carry-forward falls back to checkpoints. Rows stand while everything it reads still holds rows — a refused run carries its answers, and its readers keep theirs — and under a repair of named records, which touches only those. A store that cannot say whether an action holds rows is read as holding them. An action whose walk found no input file (`NoInputFilesError`) is skipped the same way, with `NO_INPUT_FILES`: a run that walks no file rewrites none, so the rows it stored before are deleted and its readers skip under it. | `llm`, `workflow` |
| `merge.py` | Module | Shared utilities for merging JSON records by correlation key. `merge_branch_records()` is the unified primitive for version merge and fan-in (each branch contributes only its own namespace). `merge_json_files()` reads fail-open so one corrupt file cannot abort a merge, which leaves the caller a short result and no exception — it collects the paths it dropped into the optional `unreadable` list, the only way to learn records went missing. | `workflow`, `processing` |
| `models.py` | Module | Shared data models (WorkflowRuntimeConfig, WorkflowPaths, WorkflowMetadata, ActionLogParams). | `typing`, `workflow` |
| `pipeline.py` | Module | Builds execution pipelines for run modes (batch/online) with synchronous tool/HITL handling. Writing a file clears that file's checkpoint rows and no other's, so those left belong to files not stored since. | `llm.batch`, `processing` |
| `pipeline_file_mode.py` | Module | FILE-granularity tool and HITL processing handlers extracted from `ProcessingPipeline`. Returns `ProcessingResult.failed()` when a tool returns empty output with non-empty input so the generic zero-success check in `pipeline.py` fires naturally. Assigns each output row its `source_guid`: inherited from the input it maps to, or minted here when the row has nothing to inherit (synthetic, or a parent carrying no guid) or when one input produced several rows. A minted row is stored whole (`_delta_mode: full`) and, where it inherited a correlation id, takes one derived from it — distinct per row so nothing merges it back, and equal across version branches wherever the inherited id was. In an expanded result lineage enrichment re-mints a row that named an input and re-keys it on the new guid, so that equality does not hold there; a row that named none keeps the identity minted here (#1044) and has only its correlation id replaced (#1073). It names its parent's pool-resolvable identity as `parent_source_guid`; a row that named no parent adds none and is no longer given one by lineage enrichment (#1044), and keeps whatever the envelope carried from the input standing in for its namespaces — clearing it would be honest but the FILE-mode resolver skips a row that names nothing (#1046). Separately it names, as `producer_source_guids`, every input the row consumed whose identity it does not itself carry — plural because a many-to-one output has several, and the immediate producers rather than the pool ancestor. That is what carry-forward resolves such an input through; it is a per-stage field, so it does not reach the next action. `prefilter_by_guard` evaluates each guard against the pre-scope record handed to it as `original_data`, not against the `context_scope`-shaped record the action will receive: the scope decides what the action sees, not how it is judged, and gating on it answered a clause differently per granularity. Given no originals the two lists are the same object. The scope pass can still drop a record before the guard; RECORD mode runs the same pass after the guard instead, and raises on an unenrichable record rather than skipping it (#1140). | `processing`, `workflow` |
| `runner.py` | Module | `ActionRunner` class: init, folder lookup, dependency resolution, orchestration. Delegates file-processing to `runner_file_processing`. | `llm`, `workflow` |
| `runner_file_processing.py` | Module | File walking, merging, and storage-backend processing extracted from `runner.py`. Standalone functions that take a `runner` param for instance dispatch. All three walks stop at the file limit in force — config, `--file-limit` or `AGAC_FILE_LIMIT` — and announce which door stopped them; a repair is exempt, since it walks only the files holding the records it named. A per-file failure is not fatal to the action, so any file a walk loses — one that failed processing, a branch of a merge that would not parse, a stored entry that would not read, a whole upstream whose listing failed, or one whose own `stat()` failed — marks the action's record count unknown, since a count missing those records would let a later record limit read as one that could not have dropped anything. In all three walks a lost entry also counts as *found* — in the storage walk, a listing or a read that failed — so a walk that lost every entry fails rather than reading as one that found nothing. A directory the walk cannot open is that same loss one level up, and `rglob` omitted its whole subtree without error, so both filesystem walks enumerate with `os.walk`: it names the directory that failed, which counts as one file found and none processed, and a `batch` directory is left out, its files being skipped either way. Every such test is made on the path below the walk's root, as `should_skip_item` makes it, and `is_target_directory` asks whether a directory's parent is named `target`: the directories a project sits under (`batch/`, `staging-env/`) decide nothing, where a test on the absolute path left out every staged file or never read an upstream from the store. A repair is not exempt: the store resolves record ids to staging paths with a set union, so an id resolving to nothing leaves no trace, and `_stamped_slice_outcome` short-circuits on `retried_records` anyway — so an exemption would suppress a real report and protect a count nothing reads. Deciding whether an entry is a regular file can itself fail, so that question is asked last — after every deliberate exclusion — and raises rather than answering "skip": `Path.is_file()` answers `False` for `ENOENT`/`ENOTDIR`/`EBADF`/`ELOOP`, making a lost file indistinguishable from a directory, and re-raises the rest mid-walk with no file attached. A walk that finds no file at all raises `NoInputFilesError`, so the executor skips the action rather than completing it over the rows of input that is gone; under a repair it carries on: a repair touches only the records it named, so finding nothing is no reason to delete the rest (the single-directory walk narrows to their files, which may all be gone). A file limit needs no exemption: it stops a walk only after it has taken a file. | `workflow`, `processing`, `utils` |
| `schema_service.py` | Module | `WorkflowSchemaService` that exposes input/output schema mapping. `from_action_configs` classmethod encapsulates construction + optional UDF registry and pre-scanned `tool_schemas`. | `schema`, `output` |
| `service_init.py` | Module | Service assembly and storage backend initialization extracted from coordinator. | `config`, `workflow` |
| `strategies.py` | Module | Pluggable strategies for action execution (loop/parallel). | `workflow`, `validation` |

## Design Notes

### Zero-success failure check

Both `pipeline.py` and `initial_pipeline.py` delegate to
`CollectionStats.raise_if_terminal_failure()` (in `processing/result_collector.py`).
The method uses `stats.success` rather than `not output` because EXHAUSTED records
produce tombstone data that inflates the output list despite representing zero real
successes.

This intentionally overrides `on_exhausted="return_last"` when ALL records exhaust.
`return_last` is designed for partial failures where some records succeed alongside exhausted
tombstones. When zero records succeed, tombstone-only output is not useful and downstream
actions would produce garbage. `_handle_exhausted_policy` in `ResultCollector` handles
`on_exhausted="raise"` independently (inside collection, handing the halt back).

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `AgentWorkflow.__init__()` | `agent_config/{workflow}.yml` | Reads | `name`, `actions[]`, `defaults` |
| `AgentWorkflow.__init__()` | `.env` | Reads | — |
| `AgentWorkflow.run()` | `agent_io/target/{action}/` | Writes | — |
| `AgentWorkflow._clear_for_fresh_run()` | `.agac/batch_state/` | Deletes | `--fresh` |
| `AgentWorkflow._reset_retryable_actions()` | `agent_config/{workflow}.yml` | Reads | `actions[].prompt`, `actions[].schema`, `actions[].guard`, `model_name`, `model_vendor` |
| `ActionExecutor.reopen_with_readers()` | `.agac/batch_state/` | Deletes | — |
| `AgentWorkflow._run_storage_maintenance()` | `agent_config/{workflow}.yml` | Reads | `storage.prompt_trace_retention_runs`, `storage.source_data_ttl_days` (off the raw config dict, not the validated model) |
| `AgentWorkflow.async_run()` | `agent_io/target/{action}/` | Writes | — |
| `load_workflow_configs()` | `agent_config/{workflow}.yml` | Reads | `name`, `actions[]`, `defaults` |
| `discover_workflow_udfs()` | `tools/{workflow}/*.py` | Reads | — |
| `WorkflowSchemaService.from_action_configs()` | `schema/{workflow}/{action}.yml` | Validates | `actions[].schema` |
| `WorkflowSchemaService.validate()` | `agent_config/{workflow}.yml` | Validates | `actions[].context_scope`, `actions[].schema` |
| `ActionRunner.run_action()` | `agent_io/staging/` | Reads | — |
| `ActionRunner.run_action()` | `agent_io/target/{action}/` | Writes | — |
| `ActionExecutor._drop_rows_read_from_nothing()` | `agent_io/store/{workflow_name}.db` | Reads | — |
| `ActionExecutor._forget_stored_rows()` | `agent_io/target/{action}/` | Deletes | — |
| `ProcessingPipeline` | `agent_io/target/{action}/` | Writes | `actions[].run_mode` |
| `WorkflowEventLogger` | `agent_io/target/{action}/` | Reads | — |

**Internal only**: `WorkflowRuntimeConfig`, `WorkflowPaths`, `WorkflowState`, `WorkflowMetadata`, `RuntimeContext`, `CoreServices`, `SupportServices`, `WorkflowServices`, `ActionLogParams`, `ActionExecutionResult`, `ExecutionMetrics`, `ActionRunParams`, `ExecutorDependencies`, `PipelineConfig`, `StrategyExecutionParams`, `FileProcessParams`, `ActionStrategy`, `InitialStrategy`, `StandardStrategy`, `ActionStateManager`, `ActionStatus`, `SkipEvaluator`, `BatchLifecycleManager`, `VersionOutputCorrelator`, `ActionOutputManager`, `ManifestManager`, `ActionLevelOrchestrator` — no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | Loads workflow YAML via ConfigManager and resolves project paths |
| `input` | outbound | File reading, UDF discovery, data preprocessing, and staging pipelines |
| `llm` | outbound | LLM provider calls (realtime and batch) for action execution |
| `logging` | outbound | Fires workflow/action lifecycle events and manages log context |
| `output` | outbound | Schema loading and file writing for action results |
| `processing` | outbound | Record-level processing, result collection, and dynamic agent dispatch |
| `prompt` | outbound | Context scope parsing and field-reference resolution for prompts |
| `storage` | outbound | SQLite backend for target persistence, dispositions, and state |
| `tooling` | outbound | Run tracker and documentation generation |
| `utils` | outbound | Constants, correlation IDs, UDF registry, and safe formatting |
| `validation` | outbound | Static analysis, preflight resolution, and guard condition checks |
| `errors` | outbound | Structured error types for configuration, workflow, and validation failures |
| `models` | outbound | ActionSchema and field-info models for schema service |
| `cli` | inbound | CLI `run` command creates and executes AgentWorkflow |
| `config` | inbound | Config factory creates ActionRunner used by workflow services |
