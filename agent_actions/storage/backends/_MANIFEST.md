# Storage Backends Manifest

## Overview

Concrete storage backend implementations. Currently provides SQLite backend with
architecture designed for future backends (S3, DuckDB, PostgreSQL, etc.).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package exports for backend implementations. | `typing` |
| `sqlite_backend.py` | Module | SQLite implementation of `StorageBackend` using WAL mode for concurrency. Thread-safe: `_lock` is acquired inside the `connection` property before returning the connection; `set_disposition` validates `relative_path` via `_validate_identifier` before use. | `sqlite3`, `json`, `storage.backend` |
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
