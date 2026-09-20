# Storage Manifest

**[> Architecture Deep Dive (ARCHITECTURE.md)](ARCHITECTURE.md)** — table schemas, disposition system, checkpoint model, thread safety, schema migration, caveats.

## Overview

Extensible storage backend module for workflow data persistence. Provides a pluggable
storage layer that supports SQLite (default) with architecture designed for future
backends (S3, DuckDB, etc.). One database per workflow stored at
`{workflow}/agent_io/store/{workflow_name}.db`.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [backends](backends/_MANIFEST.md) | Concrete storage backend implementations (SQLite, future: S3, DuckDB). |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Factory function and backend registry for creating storage instances. | `workflow`, `config` |
| `get_storage_backend` | Function | Factory that creates storage backend instances by type (default: sqlite). | `workflow` |
| `BACKENDS` | Dict | Registry mapping backend type names to their implementation classes. | `config` |
| `backend.py` | Module | Abstract `StorageBackend` interface defining the contract for all backends. | `abc`, `typing` |
| `StorageBackend` | ABC | Abstract base class. `read_target()` is a template method: calls `_read_target_raw()` (abstract), then validates lifecycle and resets for downstream. `read_target_for_rewrite()` shares that reconstruction but skips the downstream reset, for a caller writing an action's rows back where they came from — the reset is the truth for a consumer reading forward and a lie about an action whose output already exists. `target_rows_per_source_guid()` is a third template method over the same primitive, answering how many rows an action holds per identity without reconstructing, validating or resetting — none of which an identity needs. `source_files_for_records()` resolves stored input rows back to the staged files holding them. Subclasses implement `_read_target_raw()` only. | `abc` |

## Integration Points

- **workflow/coordinator.py**: Initializes storage backend in `AgentWorkflow.__init__`
- **workflow/runner.py**: Uses backend for dependency resolution via `list_target_files`
- **workflow/executor.py**: Verifies output exists in storage before skipping completed agents
- **workflow/pipeline.py**: Passes backend to `SourceDataLoader` for read operations
- **output/writer.py**: Uses backend for `write_target()` operations
- **output/saver.py**: Uses backend for `write_source()` operations
- **input/loaders/source_data.py**: Falls back to backend for `read_source()` operations
- **processing/task_preparer.py**: Passes backend for prompt trace writes

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `get_storage_backend()` | `agent_io/store/{workflow_name}.db` | Writes | `storage_backend` |
| `StorageBackend.write_target()` | `agent_io/target/{action}/` | Writes | — |
| `StorageBackend.read_target()` | `agent_io/target/{action}/` | Reads | — |
| `StorageBackend.read_target_for_rewrite()` | `agent_io/target/{action}/` | Reads | — |
| `StorageBackend.write_source()` | `agent_io/store/{workflow_name}.db` | Writes | — |
| `StorageBackend.read_source()` | `agent_io/store/{workflow_name}.db` | Reads | — |
| `StorageBackend.list_target_files()` | `agent_io/store/{workflow_name}.db` | Reads | — |
| `StorageBackend.source_files_for_records()` | `agent_io/store/{workflow_name}.db` | Reads | — |
| `StorageBackend.target_rows_per_source_guid()` | `agent_io/store/{workflow_name}.db` | Reads | — |
| `StorageBackend.set_disposition()` | `agent_io/store/{workflow_name}.db` | Writes | — |
| `StorageBackend.get_disposition()` | `agent_io/store/{workflow_name}.db` | Reads | — |
| `StorageBackend.delete_target()` | `agent_io/store/{workflow_name}.db` | Writes | — |
| `StorageBackend.initialize()` | `agent_io/store/{workflow_name}.db` | Writes | — |

**Internal only**: `SQLiteBackend._validate_identifier`, `SQLiteBackend._format_size`, `Disposition`, `VALID_DISPOSITIONS`, `NODE_LEVEL_RECORD_ID`, `DISPOSITION_*` constants -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | Reads storage_backend type and defaults from project config |
| `logging` | outbound | Backends mark their bookkeeping notices as framework-internal |
| `output` | inbound | FileWriter and UnifiedSourceDataSaver delegate writes to StorageBackend |
| `input` | inbound | SourceDataLoader reads from StorageBackend |
| `workflow` | inbound | Coordinator initializes backend; runner and executor query target/disposition state |
| `processing` | inbound | Processor threads storage_backend through the processing pipeline |
| `prompt` | inbound | Context scope passes output_directory for backend data resolution |
