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
| `cleaner.py` | Module | Removes a workflow's working directories during `agac clean`. With `--all` it reads the batch registry out of the store it is about to wipe and reclaims what a provider recorded locally about those batches, which nothing could find afterwards. Before it confirms or deletes anything it holds the workflow's run lock (`storage.run_lock.hold_run_lock`), in every mode once it has found something to remove, with or without a store folder (the lock creates it), so it exits with `RunInProgressError` while a run or retry is in progress, and a run that starts while it asks is refused. Whether there was a store is read before the lock. It never deletes the lock file: the store is emptied around it (`AgentManager.clean_directory(..., keep=)`), so the next run locks the same file, and Windows, which refuses to delete a file held open, cleans the same way. | `cli`, `file_io`, `llm.batch`, `storage` |
| `handlers.py` | Module | Response/stream handlers for processing online outputs and streaming events. `AgentManager.get_agent_paths` accepts `project_root: Path \| None`. Delegates root discovery to `utils.project_root`. `AgentManager.clean_directory(agent, directory, keep=None)` removes the directory, or everything in it but `keep` when `keep` is directly inside it (the run lock file `clean` holds). | `logging`, `output` |
| `output.py` | Module | Emits online outputs, handling side outputs, metadata, and retry loops. `OutputHandler.output_path` is where `save_main_output` writes a file's output, and `pipeline.py` names the file's stored rows from the same path, so the action's reads and its write cannot drift apart. | `output`, `processing` |
