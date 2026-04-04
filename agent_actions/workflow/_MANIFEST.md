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
| `pipeline_file_mode.py` | Module | FILE-granularity tool and HITL processing handlers extracted from `ProcessingPipeline`. Returns `ProcessingResult.failed()` when a tool returns empty output with non-empty input so the generic zero-success check in `pipeline.py` fires naturally. | `processing`, `workflow` |
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

## Project Surface

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `load_workflow_configs()` | `agent_config/{workflow}.yml` | Reads | `name`, `actions`, `defaults` |
| `load_workflow_configs()` | `agent_config/{workflow}.yml` | Validates | `actions[].dependencies`, `actions[].context_scope` |
| `discover_workflow_udfs()` | `tools/{workflow}/*.py` | Reads | `defaults.tool_path` |
| `AgentWorkflow.__init__()` | `agent_io/target/{workflow}.db` | Writes | — |
| `AgentWorkflow.run()` | `agent_io/target/{action}/` | Writes | `actions[].name` |
| `AgentWorkflow.run()` | `agent_io/staging/` | Reads | `defaults.data_source` |
| `AgentWorkflow._run_static_validation()` | `agent_config/{workflow}.yml` | Validates | `actions[].schema`, `actions[].context_scope` |
| `ActionRunner.setup_directories()` | `agent_io/target/{action}/` | Writes | `actions[].name` |
| `ActionRunner._resolve_start_node_directories()` | `agent_io/staging/` | Reads | `defaults.data_source` |
| `ActionRunner._resolve_dependency_directories()` | `agent_io/target/{dependency}/` | Reads | `actions[].dependencies` |
| `WorkflowSchemaService.validate()` | `schema/{workflow}/{schema_name}.yml` | Reads | `actions[].schema` |
| `WorkspaceIndex.scan_workspace()` | `agent_config/{workflow}.yml` | Reads | `actions[].dependencies[*].workflow` |
| `ActionExecutor.execute_action_sync()` | `agent_io/target/{action}/` | Writes | `actions[].name` |
| `ActionStateManager` | `agent_io/.agent_status.json` | Writes | — |

**Internal only**: `_run_config_stage()`, `_strip_unreachable_drops()`, `_get_reachable_actions()`, `_generate_workflow_session_id()` — no direct project surface.

**Examples** — see this module in action:
- [`examples/incident_triage/.../incident_triage.yml`](../../examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml) — workflow with parallel versioned classifiers, fan-in aggregation, guard-based conditional escalation, and seed data injection
- [`examples/review_analyzer/.../review_analyzer.yml`](../../examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml) — multi-vendor model selection, parallel consensus scoring with version_consumption merge, and pre-check quality gates
- [`examples/contract_reviewer/.../contract_reviewer.yml`](../../examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml) — map-reduce pattern with FILE granularity aggregation, guard-based deep analysis for high-risk clauses
- [`examples/incident_triage/tools/incident_triage/aggregate_severity_votes.py`](../../examples/incident_triage/tools/incident_triage/aggregate_severity_votes.py) — UDF tool discovered by `discover_workflow_udfs()` at startup
- [`examples/incident_triage/.../seed_data/team_roster.json`](../../examples/incident_triage/agent_workflow/incident_triage/seed_data/team_roster.json) — seed data loaded via `defaults.context_scope.seed_path`
