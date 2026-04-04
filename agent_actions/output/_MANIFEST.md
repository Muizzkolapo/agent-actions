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
| `file_handler.py` | Module | Backward-compatibility shim — re-exports `FileHandler` from `utils.file_handler`. | `utils.file_handler` |
| `saver.py` | Module | Persistent saver for workflow outputs and guard results. | `workflow`, `logging` |
| `writer.py` | Module | FileWriter for staging/target/source outputs with optional storage backend and relative-path preservation. | `output.response`, `logging` |

## FileWriter Interface

The `FileWriter` class supports database-backed persistence via storage backends.

### Constructor

```python
FileWriter(
    file_path: str,
    storage_backend: Optional[StorageBackend] = None,
    action_name: Optional[str] = None,
    output_directory: Optional[str] = None,
)
```

| Parameter | Description |
|-----------|-------------|
| `file_path` | Full path to the output file |
| `storage_backend` | Optional storage backend for database persistence |
| `action_name` | Node/agent name for backend writes (required if storage_backend provided) |
| `output_directory` | Base directory for computing relative paths (preserves subdirectory structure) |

### Relative Path Preservation

When `output_directory` is provided, `write_target()` computes the relative path from
`output_directory` to `file_path`, preserving subdirectory structure in the storage backend.

**Example:**
- `file_path`: `/project/agent_io/target/agent_1/subdir/file.json`
- `output_directory`: `/project/agent_io/target/agent_1`
- Stored as: `subdir/file.json` (not just `file.json`)

This prevents file collisions when multiple files share the same name but live in different subdirectories.

## Project Surface

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `FileWriter.write_staging()` | `agent_io/staging/*.json` | Writes | — |
| `FileWriter.write_staging()` | `agent_io/staging/*.txt` | Writes | — |
| `FileWriter.write_staging()` | `agent_io/staging/*.csv` | Writes | — |
| `FileWriter.write_target()` | `agent_io/target/{workflow}.db` | Writes | — |
| `FileWriter.write_source()` | `agent_io/source/*.json` | Writes | — |
| `UnifiedSourceDataSaver.save_source_items()` | `agent_io/target/{workflow}.db` | Writes | — |
| `SchemaLoader.discover_schema_files()` | `schema/{workflow}/*.yml` | Reads | `schema_path` |
| `SchemaLoader.load_schema()` | `schema/{workflow}/{schema_name}.yml` | Reads | `schema_name` |
| `ResponseSchemaCompiler.compile()` | `schema/{workflow}/{schema_name}.yml` | Reads | `schema_name`, `schema` |
| `ActionExpander.expand()` | `agent_config/{workflow}.yml` | Transforms | `kind`, `model_vendor`, `schema_name`, `context_scope` |
| `inherit_simple_fields()` | `agent_config/{workflow}.yml` | Reads | all keys in `SIMPLE_CONFIG_FIELDS` |
| `ResponseBuilder.build()` | `agent_io/target/{action}/*.json` | Transforms | `output_field` |

**Internal only**: `_convert_json_schema_to_unified()`, `compile_field()`, `compile_unified_schema()` — internal schema conversion with no direct project file surface. `_inject_functions_into_schema()`, `_resolve_dispatch_in_schema()` — dispatch resolution internals.

**Examples** — see this module in action:
- [`examples/product_listing_enrichment/agent_workflow/product_listing_enrichment/agent_io/target/`](../../examples/product_listing_enrichment/agent_workflow/product_listing_enrichment/agent_io/target/) — target output directory written by `FileWriter.write_target()`
- [`examples/product_listing_enrichment/agent_workflow/product_listing_enrichment/schema/`](../../examples/product_listing_enrichment/agent_workflow/product_listing_enrichment/schema/) — response schemas loaded by `SchemaLoader`
- [`examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_io/source/`](../../examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_io/source/) — source data persisted by `UnifiedSourceDataSaver`
