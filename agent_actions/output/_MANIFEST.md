# Output Manifest

## Overview

Writes processed workflow outputs (main/side files) and response artifacts while
serving schema/guard metadata to downstream tooling.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [response](response/_MANIFEST.md) | Schema-aware response loaders, expander, and config helpers. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `file_handler.py` | Module | Helpers for writing output files and ensuring directories exist. | `file_io`, `logging` |
| `saver.py` | Module | Persistent saver for workflow outputs and guard results. | `workflow`, `logging` |
| `writer.py` | Module | Stream-based writer that serializes JSON/YAML responses. | `output.response`, `logging` |
