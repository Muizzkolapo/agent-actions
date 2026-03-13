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
