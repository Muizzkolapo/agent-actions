# Utils Manifest

## Overview

Shared helpers for IDs, field management, metadata, lineage, UDF tooling, path
handling, formatting, and transformation utilities used by both CLI and runtime
pathways.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [correlation](correlation/_MANIFEST.md) | Version correlation ID generation for deterministic versioned-agent workflows. |
| [field_management](field_management/_MANIFEST.md) | Ensures processed items always expose the required metadata/IDs. |
| [id_generation](id_generation/_MANIFEST.md) | UUID/ deterministic ID helpers for target/node/source GUIDs. |
| [lineage](lineage/_MANIFEST.md) | Lineage tracking helpers (chain building, ancestry chain propagation). |
| [metadata](metadata/_MANIFEST.md) | Unified metadata extraction/ dataclasses for LLM responses. |
| [transformation](transformation/_MANIFEST.md) | Passthrough transformer + strategy helpers for context_scope.passthrough data. |
| [udf_management](udf_management/_MANIFEST.md) | UDF discovery, registry, and dynamic execution helpers. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `constants.py` | Module | Shared configuration key constants and reserved names used across CLI/workflows. | `configuration`, `validation` |
| `dict.py` | Module | `get_nested_value` helper for safely reading dot-separated fields from nested dicts. | `filtering`, `preprocessing` |
| `graph_utils.py` | Module | Graph algorithms for dependency resolution (`topological_sort`). | `errors` |
| `module_loader.py` | Module | Thread-safe module loading and UDF discovery (`load_module_from_path`, `load_module_from_directory`, `discover_and_load_udfs`). No `sys.path` mutation. | `logging`, `errors`, `utils.udf_management` |
| `passthrough_builder.py` | Module | `PassthroughItemBuilder` that creates normalized passthrough objects with metadata and lineage for batch/online modes. | `preprocessing`, `lineage`, `id_generation` |
| `path_utils.py` | Module | Convenience path helpers (ensure dirs, mirror target-to-source, resolve absolute paths, find project root) backed by `PathManager`. Thread-safe global singleton with double-checked locking. `set_path_manager()` allows explicit DI of a scoped instance. `derive_workflow_root()` safely finds the workflow root from a path inside a workflow (agent_io fast-path + agent_config walk-up + safe fallback). | `config.paths`, `file_io` |
| `safe_format.py` | Module | Robust exception formatting (safe formatting, root cause extraction, chain formatting). | `logging`, `errors` |
| `tools_resolver.py` | Module | Normalizes the various `tools`/`tool_path` syntaxes in agent configs. | `configuration`, `validation` |
| `error_handler.py` | Module | Error handling utilities for configuration and validation errors. | `errors`, `logging` |
| `error_wrap.py` | Module | Decorator for wrapping validation errors with additional context. | `errors`, `validation` |
| `file_handler.py` | Module | `FileHandler` static utility for recursive file/folder discovery (stdlib only: logging, os, pathlib). Moved from `output/`. | `file_io` |
| `project_root.py` | Module | Project root detection utilities (`find_project_root`, `ensure_in_project`). Moved from `cli/`. | `errors` |
