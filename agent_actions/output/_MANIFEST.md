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

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `FileWriter.write_target()` | `agent_io/target/{action}/` | Writes | — |
| `FileWriter.write_staging()` | `agent_io/staging/` | Writes | — |
| `FileWriter.write_source()` | `agent_io/staging/` | Writes | — |
| `UnifiedSourceDataSaver.save_source_items()` | `agent_io/target/{action}/` | Writes | — |
| `SchemaLoader.load_schema()` | `schema/{workflow}/{action}.yml` | Reads | `schema_path` |
| `SchemaLoader.discover_schema_files()` | `schema/{workflow}/{action}.yml` | Reads | `schema_path` |
| `ActionExpander.expand()` | `agent_config/{workflow}.yml` | Transforms | `actions`, `defaults`, `versions` |
| `ResponseSchemaCompiler.compile()` | `schema/{workflow}/{action}.yml` | Reads | `schema`, `schema_name` |
| `ResponseBuilder.build()` | `agent_io/target/{action}/` | Writes | — |

**Internal only**: `compile_unified_schema`, `_convert_json_schema_to_unified`, `compile_field`, `_inject_functions_into_schema`, `_resolve_dispatch_in_schema`, `_prepare_context_data_str`, `config_fields`, `config_schema`, `expander_validation`, `expander_schema`, `expander_action_types`, `expander_merge`, `expander_guard_validation`, `schema_conversion`, `vendor_compilation`, `dispatch_injection`, `context_data` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `storage` | outbound | FileWriter delegates persistence to StorageBackend.write_target |
| `config` | outbound | Reads schema_path and action configuration from project config |
| `logging` | outbound | Fires file-write and schema-load observability events |
| `guards` | outbound | Guard parser and consolidated guard used by response expander |
| `workflow` | inbound | Workflow pipeline uses FileWriter and saver for action output |
| `input` | inbound | Initial-stage pipeline uses FileWriter and UnifiedSourceDataSaver |
| `validation` | inbound | Schema validation consumes SchemaLoader and ActionExpander |
| `prompt` | inbound | Prompt context uses schema compilation for dispatch injection |
