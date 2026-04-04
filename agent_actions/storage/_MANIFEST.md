# Storage Manifest

## Overview

Extensible storage backend module for workflow data persistence. Provides a pluggable
storage layer that supports SQLite (default) with architecture designed for future
backends (S3, DuckDB, etc.). One database per workflow stored at
`{workflow}/agent_io/target/{workflow_name}.db`.

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
| `StorageBackend` | ABC | Abstract base class with methods: `initialize`, `write_target`, `read_target`, `write_source`, `read_source`, `list_target_files`, `list_source_files`, `set_disposition`, `get_disposition`, `has_disposition`, `clear_disposition`, `close`. | `abc` |

## Integration Points

- **workflow/coordinator.py**: Initializes storage backend in `AgentWorkflow.__init__`
- **workflow/runner.py**: Uses backend for dependency resolution via `list_target_files`
- **workflow/executor.py**: Verifies output exists in storage before skipping completed agents
- **workflow/pipeline.py**: Passes backend to `SourceDataLoader` for read operations
- **output/writer.py**: Uses backend for `write_target()` operations
- **output/saver.py**: Uses backend for `write_source()` operations
- **input/loaders/source_data.py**: Falls back to backend for `read_source()` operations
- **input/context/historical.py**: Queries backend for historical node data lookups
- **prompt/context/scope.py**: Passes `output_directory` for backend data resolution
- **processing/processor.py**: Threads `output_directory` through prompt preparation

## Project Surface

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `get_storage_backend()` | `agent_io/target/{workflow}.db` | Writes | `storage_backend` |
| `SQLiteBackend.initialize()` | `agent_io/target/{workflow}.db` | Writes | — |
| `SQLiteBackend.write_target()` | `agent_io/target/{workflow}.db` | Writes | — |
| `SQLiteBackend.read_target()` | `agent_io/target/{workflow}.db` | Reads | — |
| `SQLiteBackend.write_source()` | `agent_io/target/{workflow}.db` | Writes | — |
| `SQLiteBackend.read_source()` | `agent_io/target/{workflow}.db` | Reads | — |
| `SQLiteBackend.list_target_files()` | `agent_io/target/{workflow}.db` | Reads | — |
| `SQLiteBackend.list_source_files()` | `agent_io/target/{workflow}.db` | Reads | — |
| `SQLiteBackend.set_disposition()` | `agent_io/target/{workflow}.db` | Writes | — |
| `SQLiteBackend.get_disposition()` | `agent_io/target/{workflow}.db` | Reads | — |
| `SQLiteBackend.delete_target()` | `agent_io/target/{workflow}.db` | Writes | — |
| `SQLiteBackend.preview_target()` | `agent_io/target/{workflow}.db` | Reads | — |
| `SQLiteBackend.get_storage_stats()` | `agent_io/target/{workflow}.db` | Reads | — |

**Internal only**: `StorageBackend` (ABC) — abstract interface, no direct file interaction. `Disposition` enum, `VALID_DISPOSITIONS`, `NODE_LEVEL_RECORD_ID` — constants consumed by workflow/processing modules, no project file surface. `SQLiteBackend._validate_identifier()` — internal security helper.

**Examples** — see this module in action:
- [`examples/product_listing_enrichment/agent_workflow/product_listing_enrichment/agent_io/target/`](../../examples/product_listing_enrichment/agent_workflow/product_listing_enrichment/agent_io/target/) — target directory containing `{workflow}.db` created by `get_storage_backend()`
- [`examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_io/target/`](../../examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_io/target/) — SQLite database storing source/target data and disposition records
- [`examples/support_resolution/agent_workflow/support_resolution/agent_io/target/`](../../examples/support_resolution/agent_workflow/support_resolution/agent_io/target/) — multi-action workflow demonstrating `list_target_files()` for dependency resolution
