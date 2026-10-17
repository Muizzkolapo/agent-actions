# Storage Backends Manifest

## Overview

Concrete storage backend implementations. Currently provides SQLite backend with
architecture designed for future backends (S3, DuckDB, PostgreSQL, etc.).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package exports for backend implementations. | `typing` |
| `sqlite_backend.py` | Module | SQLite implementation of `StorageBackend` using WAL mode for concurrency. Thread-safe: `_lock` is acquired inside the `connection` property before returning the connection; `set_disposition` validates `relative_path` via `_validate_identifier` before use. `has_target_file` is a `SELECT 1 … LIMIT 1` point read. `delete_target` removes the action's `batch_file_names:{action}` metadata in the same transaction as its rows. `delete_target_files` deletes the files named in one transaction and clears the reconstruction cache, which would otherwise serve a deleted file to a read in the same process. `stored_path` applies `_validate_identifier`'s rewrite (surrounding whitespace stripped, a backslash turned into `/`), and gives back unchanged a name it would refuse. `save_checkpoint_records` keeps one `checkpoint_output` row per `source_guid`, holding the list of every row given under it, since an expansion's rows share their input's until enrichment; `read_checkpoint_records` returns those rows flat, and reads a row an earlier version stored as one record; `checkpointed_without_row_count` names the records held that way, since that version kept only the last of an expansion's rows. `get_terminal_record_ids` leaves out a `passthrough` whose reason is `guard_skip`, which earlier versions wrote for an online guard skip: a skip answers nothing, so the gate sends the record on to the guard's verdict. `clear_dispositions_batch` deletes an action's dispositions under many record ids in one transaction, chunked under the parameter limit. Source, target and checkpoint rows are encoded and decoded with `utils.deep_json`, so a row's nesting depth does not limit the store; `records_share_a_repeat_chain` asks SQLite's JSON functions only about rows they can parse (`json_valid`) and reads the rest — a row 1000 levels deep, or one holding a NaN — in Python, rather than failing the whole query. | `sqlite3`, `json`, `utils.deep_json`, `storage.backend`, `record` |
| `SQLiteBackend` | Class | Stores source/target data in SQLite with deduplication by `source_guid`. Tables: `source_data`, `target_data`, `record_disposition`. | `storage.backend` |

## SQLite Schema

```sql
CREATE TABLE source_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    relative_path TEXT NOT NULL,
    source_guid TEXT NOT NULL,
    data TEXT NOT NULL,  -- JSON blob
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(relative_path, source_guid)
);

CREATE TABLE target_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    data TEXT NOT NULL,  -- JSON blob
    record_count INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(action_name, relative_path)
);

CREATE TABLE record_disposition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    record_id TEXT NOT NULL,  -- "__node__" for node-level signals
    disposition TEXT NOT NULL, -- "passthrough", "skipped", "filtered", "exhausted", "failed", "unprocessed"
    reason TEXT,
    relative_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(action_name, record_id, disposition)
);
```

## Adding New Backends

To add a new backend (e.g., S3, DuckDB):

1. Create `{backend_name}_backend.py` in this directory
2. Implement `StorageBackend` abstract class from `agent_actions.storage.backend`
3. Register in `agent_actions/storage/__init__.py`:
   ```python
   from agent_actions.storage.backends.{backend_name}_backend import {BackendName}Backend
   BACKENDS["{backend_name}"] = {BackendName}Backend
   ```
4. Add initialization logic in `get_storage_backend()` factory
