# Storage Backends Manifest

## Overview

Concrete storage backend implementations. Currently provides SQLite backend with
architecture designed for future backends (S3, DuckDB, PostgreSQL, etc.).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package exports for backend implementations. | `typing` |
| `sqlite_backend.py` | Module | SQLite implementation of `StorageBackend` using WAL mode for concurrency. Thread-safe: `_lock` is acquired inside the `connection` property before returning the connection; `set_disposition` validates `relative_path` via `_validate_identifier` before use. `has_target_file` is a `SELECT 1 … LIMIT 1` point read. `delete_target` removes the action's `batch_file_names:{action}` metadata in the same transaction as its rows. `delete_target_files` deletes the files named in one transaction and clears the reconstruction cache, which would otherwise serve a deleted file to a read in the same process. `stored_path` applies `_validate_identifier`'s rewrite (surrounding whitespace stripped, a backslash turned into `/`), and gives back unchanged a name it would refuse. `save_checkpoint_records` keeps one `checkpoint_output` row per `source_guid`, holding the list of every row given under it, since an expansion's rows share their input's until enrichment; `read_checkpoint_records` returns those rows flat, and reads a row an earlier version stored as one record; `checkpointed_without_row_count` names the records held that way, since that version kept only the last of an expansion's rows. Writing a file (`_write_target_raw`) deletes that file's checkpoint rows in the same transaction, online or batch, so a row left beside a stored file is always an answer given after it. `get_terminal_record_ids` leaves out a `passthrough` whose reason is `guard_skip`, which earlier versions wrote for an online guard skip: a skip answers nothing, so the gate sends the record on to the guard's verdict. `clear_dispositions_batch` deletes an action's dispositions under many record ids in one transaction, chunked under the parameter limit. Source, target and checkpoint rows are encoded and decoded with `utils.deep_json`, so a row's nesting depth does not limit the store; `write_source` stores the guid a row repeats in `source_data.repeat_of_source_guid` (`''` when it repeats nothing), indexed by `idx_source_repeat_of`, so `records_share_a_repeat_chain` answers both directions with one indexed query and decodes nothing. A NULL there is a row written before the column existed (or holding a value the column cannot carry): for those rows only, it asks SQLite's JSON functions about the text rows they can parse (`json_valid`) and reads the rest — compressed, 1000 levels deep, or holding a NaN — in Python, rather than failing the whole query. `target_data.data`, `source_data.data`, `checkpoint_output.record_data` and `record_disposition.input_snapshot` are stored as zlib blobs, each against the dictionary in `prompt_trace_dictionary` keyed `(action, "<table>.<column>")` and made from the first value written (source rows share one under an empty action); `decode_payload` reads them back, raising `SerializationError` naming the row for a value it cannot read, and a row stored as text still reads. `delete_target`, `clear_source_data`, and a `clear_checkpoint_records` or `clear_disposition` with no filter drop the dictionary with the last row it served. `actions_with_dispositions` lists the actions holding a disposition row; `get_disposition(snapshots=False)` leaves `input_snapshot` out and decodes nothing, for the run paths that read only ids and dispositions. | `sqlite3`, `json`, `zlib`, `utils.deep_json`, `storage.backend`, `record`, `errors.processing` |
| `SQLiteBackend` | Class | Stores source/target data in SQLite with deduplication by `source_guid`. Tables: `source_data`, `target_data`, `record_disposition`. | `storage.backend` |

## SQLite Schema

```sql
CREATE TABLE source_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    relative_path TEXT NOT NULL,
    source_guid TEXT NOT NULL,
    data TEXT NOT NULL,  -- JSON blob
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    repeat_of_source_guid TEXT DEFAULT NULL,  -- '' = repeats nothing; NULL = read data
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
