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
| `coordinator.py` | Module | Coordinates workflow execution order, dependencies, and validation. | `validation`, `workflow` |
| `executor.py` | Module | Handles running actions (LLM/tool/HITL) and interfacing with processors. | `llm`, `workflow` |
| `merge.py` | Module | Shared utilities for merging JSON records by correlation key. | `workflow`, `processing` |
| `models.py` | Module | Shared data models (WorkflowConfig, ActionConfig, AgentWorkflow). | `typing`, `workflow` |
| `pipeline.py` | Module | Builds execution pipelines for run modes (batch/realtime) with synchronous tool/HITL handling. | `llm.batch`, `processing` |
| `runner.py` | Module | High-level runner (BatchRunner/RealtimeRunner) entrypoints. `AgentRunner.get_agent_folder` accepts `project_root: Path \| None`. | `llm`, `workflow` |
| `schema_service.py` | Module | `WorkflowSchemaService` that exposes input/output schema mapping. | `schema`, `output` |
| `strategies.py` | Module | Pluggable strategies for action execution (loop/parallel). | `workflow`, `validation` |
| `workspace_index.py` | Module | Index of files/workflow directories (used by tooling). | `tooling`, `file_io` |
