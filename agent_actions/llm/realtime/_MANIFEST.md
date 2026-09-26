# Online (realtime/) Manifest

## Overview

Online helpers power the online runner (builder/handlers/output) that processes
LLM actions with low latency, integrates guard filters, and emits results with
metadata.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [services](services/_MANIFEST.md) | Context, prompt, schema, and invocation helpers for online runs. |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `Cleaner._release_batch_records()` | `.agac/batch_state/` | Deletes (`{batch_id}.json` and abandoned `*.tmp`) | `--all` |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `builder.py` | Module | Constructs the online workflow builder that wires agents, guards, and prompts. | `workflow`, `preprocessing` |
| `cleaner.py` | Module | Removes a workflow's working directories during `agac clean`. With `--all` it reads the batch registry out of the store it is about to wipe and reclaims what a provider recorded locally about those batches, which nothing could find afterwards. | `cli`, `file_io`, `llm.batch`, `storage` |
| `handlers.py` | Module | Response/stream handlers for processing online outputs and streaming events. `AgentManager.get_agent_paths` accepts `project_root: Path \| None`. Delegates root discovery to `utils.project_root`. | `logging`, `output` |
| `output.py` | Module | Emits online outputs, handling side outputs, metadata, and retry loops. | `output`, `processing` |
