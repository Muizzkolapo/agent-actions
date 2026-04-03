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
| `merge.py` | Module | Shared utilities for merging JSON records by correlation key. | `workflow`, `processing` |
| `models.py` | Module | Shared data models (WorkflowRuntimeConfig, WorkflowPaths, WorkflowMetadata, ActionLogParams). | `typing`, `workflow` |
| `pipeline.py` | Module | Builds execution pipelines for run modes (batch/online) with synchronous tool/HITL handling. | `llm.batch`, `processing` |
| `pipeline_file_mode.py` | Module | FILE-granularity tool and HITL processing handlers extracted from `ProcessingPipeline`. | `processing`, `workflow` |
| `runner.py` | Module | `ActionRunner` class: init, folder lookup, dependency resolution, orchestration. Delegates file-processing to `runner_file_processing`. | `llm`, `workflow` |
| `runner_file_processing.py` | Module | File walking, merging, and storage-backend processing extracted from `runner.py`. Standalone functions that take a `runner` param for instance dispatch. | `workflow`, `processing` |
| `schema_service.py` | Module | `WorkflowSchemaService` that exposes input/output schema mapping. `from_action_configs` classmethod encapsulates construction + optional UDF registry and pre-scanned `tool_schemas`. | `schema`, `output` |
| `service_init.py` | Module | Service assembly and storage backend initialization extracted from coordinator. | `config`, `workflow` |
| `strategies.py` | Module | Pluggable strategies for action execution (loop/parallel). | `workflow`, `validation` |
| `workspace_index.py` | Module | `WorkspaceIndex`: scans workflow dirs to build dependency graphs. Config file glob uses `sorted()` for deterministic selection. | `tooling`, `file_io` |

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
