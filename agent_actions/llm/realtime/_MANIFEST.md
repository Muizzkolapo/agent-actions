# Realtime Manifest

## Overview

Realtime helpers power the online runner (builder/handlers/output) that processes
LLM actions with low latency, integrates guard filters, and emits results with
metadata.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [services](services/_MANIFEST.md) | Context, prompt, schema, and invocation helpers for realtime runs. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `builder.py` | Module | Constructs the realtime workflow builder that wires agents, guards, and prompts. | `workflow`, `preprocessing` |
| `cleaner.py` | Module | Removes temporary directories during `agac clean`. | `cli`, `file_io` |
| `config.py` | Module | Realtime-specific configuration options/defaults with kind-to-vendor normalization. | `validation`, `llm` |
| `handlers.py` | Module | Response/stream handlers for processing realtime outputs and streaming events. | `logging`, `output` |
| `output.py` | Module | Emits realtime outputs, handling side outputs, metadata, and retry loops. | `output`, `processing` |
