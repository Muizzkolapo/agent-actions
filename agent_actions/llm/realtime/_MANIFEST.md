# Online (realtime/) Manifest

## Overview

Online helpers power the online runner (builder/handlers/output) that processes
LLM actions with low latency, integrates guard filters, and emits results with
metadata.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [services](services/_MANIFEST.md) | Context, prompt, schema, and invocation helpers for online runs. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `builder.py` | Module | Constructs the online workflow builder that wires agents, guards, and prompts. | `workflow`, `preprocessing` |
| `cleaner.py` | Module | Removes temporary directories during `agac clean`. | `cli`, `file_io` |
| `handlers.py` | Module | Response/stream handlers for processing online outputs and streaming events. `AgentManager.get_agent_paths` accepts `project_root: Path \| None`. Delegates root discovery to `utils.project_root`. | `logging`, `output` |
| `output.py` | Module | Emits online outputs, handling side outputs, metadata, and retry loops. | `output`, `processing` |
