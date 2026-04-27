# Workflow Manifest

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
| `coordinator.py` | Module | Orchestration-only facade: delegates config, services, and events to extracted modules. Stores `schema_service` for reuse by callers. Raises `ConfigurationError` when `storage_backend` is `None` after service init. | `workflow` |
| `execution_events.py` | Module | `WorkflowEventLogger` class encapsulating all workflow/action event firing. | `logging`, `events` |
| `executor.py` | Module | Handles running actions (LLM/tool/HITL) and interfacing with processors. | `llm`, `workflow` |
| `merge.py` | Module | Shared utilities for merging JSON records by correlation key. `merge_branch_records()` is the unified primitive for version merge and fan-in (each branch contributes only its own namespace). | `workflow`, `processing` |
| `models.py` | Module | Shared data models (WorkflowRuntimeConfig, WorkflowPaths, WorkflowMetadata, ActionLogParams). | `typing`, `workflow` |
| `pipeline.py` | Module | Builds execution pipelines for run modes (batch/online) with synchronous tool/HITL handling. | `llm.batch`, `processing` |
| `pipeline_file_mode.py` | Module | FILE-granularity tool and HITL processing handlers extracted from `ProcessingPipeline`. Returns `ProcessingResult.failed()` when a tool returns empty output with non-empty input so the generic zero-success check in `pipeline.py` fires naturally. | `processing`, `workflow` |
| `runner.py` | Module | `ActionRunner` class: init, folder lookup, dependency resolution, orchestration. Delegates file-processing to `runner_file_processing`. | `llm`, `workflow` |
| `runner_file_processing.py` | Module | File walking, merging, and storage-backend processing extracted from `runner.py`. Standalone functions that take a `runner` param for instance dispatch. | `workflow`, `processing` |
| `schema_service.py` | Module | `WorkflowSchemaService` that exposes input/output schema mapping. `from_action_configs` classmethod encapsulates construction + optional UDF registry and pre-scanned `tool_schemas`. | `schema`, `output` |
| `service_init.py` | Module | Service assembly and storage backend initialization extracted from coordinator. | `config`, `workflow` |
| `strategies.py` | Module | Pluggable strategies for action execution (loop/parallel). | `workflow`, `validation` |

## Design Notes

### Zero-success failure check (`pipeline.py`)

Both `pipeline.py` and `initial_pipeline.py` raise `RuntimeError` when `stats.success == 0`
and `stats.failed + stats.exhausted > 0`. This uses `stats.success` rather than `not output`
because EXHAUSTED records produce tombstone data that inflates the output list despite
representing zero real successes.

This intentionally overrides `on_exhausted="return_last"` when ALL records exhaust.
`return_last` is designed for partial failures where some records succeed alongside exhausted
tombstones. When zero records succeed, tombstone-only output is not useful and downstream
actions would produce garbage. `_check_exhausted_raise` in `ResultCollector` handles
`on_exhausted="raise"` independently (runs before collection).

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `AgentWorkflow.__init__()` | `agent_config/{workflow}.yml` | Reads | `name`, `actions[]`, `defaults` |
| `AgentWorkflow.__init__()` | `.env` | Reads | — |
| `AgentWorkflow.run()` | `agent_io/target/{action}/` | Writes | — |
| `AgentWorkflow.async_run()` | `agent_io/target/{action}/` | Writes | — |
| `load_workflow_configs()` | `agent_config/{workflow}.yml` | Reads | `name`, `actions[]`, `defaults` |
| `discover_workflow_udfs()` | `tools/{workflow}/*.py` | Reads | — |
| `WorkflowSchemaService.from_action_configs()` | `schema/{workflow}/{action}.yml` | Validates | `actions[].schema` |
| `WorkflowSchemaService.validate()` | `agent_config/{workflow}.yml` | Validates | `actions[].context_scope`, `actions[].schema` |
| `ActionRunner.run_action()` | `agent_io/staging/` | Reads | — |
| `ActionRunner.run_action()` | `agent_io/target/{action}/` | Writes | — |
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
