# Storage Module Architecture

This document maps the moving parts of `agent_actions/storage/` — the module that provides durable persistence for workflow data, dispositions, prompt traces, and checkpoint state. Everything lives in a single SQLite database per workflow.

---

## High-Level Overview

```
                      agent_actions/storage/
                            │
              ┌─────────────┼─────────────┐
              │             │             │
         __init__.py    backend.py    backends/
        (factory +     (abstract      (concrete
         registry)      interface)     implementations)
              │             │             │
              │             │        sqlite_backend.py
              │             │         (the only backend
              │             │          today)
              └──────┬──────┘
                     │
              One DB per workflow:
          {workflow}/agent_io/store/{name}.db
```

The module has three parts:

| File | What it does |
|------|-------------|
| `__init__.py` | Factory function `get_storage_backend()` and `BACKENDS` registry (`{"sqlite": SQLiteBackend}`) |
| `backend.py` | Abstract `StorageBackend` base class — defines the contract for all backends |
| `backends/sqlite_backend.py` | The SQLite implementation — the only concrete backend |

The architecture is designed for future backends (S3, DuckDB), but today SQLite is the only one. All callers go through the abstract interface; none import `SQLiteBackend` directly except the factory.

---

## Table Schemas

The SQLite backend creates five tables. All are created in `initialize()` via `CREATE TABLE IF NOT EXISTS`.

### 1. source_data — ingested input records

```sql
CREATE TABLE IF NOT EXISTS source_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    relative_path TEXT NOT NULL,
    source_guid TEXT NOT NULL,
    data TEXT NOT NULL,               -- JSON blob: the full input record
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(relative_path, source_guid)
)
```

Index: `idx_source_path ON source_data(relative_path)`

Deduplication: `INSERT OR IGNORE` when `enable_deduplication=True` (default), `INSERT OR REPLACE` otherwise. Keyed on `(relative_path, source_guid)`.

### 2. target_data — action output records

```sql
CREATE TABLE IF NOT EXISTS target_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    data TEXT NOT NULL,                -- JSON blob: list[dict] of ALL records for this path
    record_count INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(action_name, relative_path)
)
```

No additional indexes — the UNIQUE constraint provides one.

The `data` column stores the **entire list of records** as a single JSON blob, not one row per record. This is a blob model: `write_target()` serializes the full `list[dict]` with `json.dumps()`, and `_read_target_raw()` deserializes it back. `record_count` is a denormalized count stored alongside for efficient stats queries.

### 3. record_disposition — per-record processing status

```sql
CREATE TABLE IF NOT EXISTS record_disposition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    record_id TEXT NOT NULL,
    disposition TEXT NOT NULL,
    reason TEXT,
    detail TEXT,                       -- extended error message or context
    relative_path TEXT,
    input_snapshot TEXT,               -- JSON of input record (capped at 10KB)
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(action_name, record_id, disposition)
)
```

Indexes:
- `idx_disp_action ON record_disposition(action_name)`
- `idx_disp_action_disp ON record_disposition(action_name, disposition)`
- `idx_disp_action_record ON record_disposition(action_name, record_id)`

### 4. prompt_trace — LLM call telemetry

```sql
CREATE TABLE IF NOT EXISTS prompt_trace (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    record_id TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    compiled_prompt TEXT NOT NULL,
    llm_context TEXT,
    response_text TEXT,
    model_name TEXT,
    model_vendor TEXT,
    run_mode TEXT,
    prompt_length INTEGER,            -- length of original prompt before truncation
    context_length INTEGER,
    response_length INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(action_name, record_id, attempt)
)
```

Indexes:
- `idx_trace_action ON prompt_trace(action_name)`
- `idx_trace_action_record ON prompt_trace(action_name, record_id)`

Large fields (prompt, context, response) are capped at 1MB (`_MAX_TRACE_FIELD_SIZE`). Overflow is replaced with `{"__truncated__": true, "original_length": N}`.

### 5. checkpoint_output — incremental online resume

```sql
CREATE TABLE IF NOT EXISTS checkpoint_output (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    source_guid TEXT,
    record_data TEXT NOT NULL,         -- JSON blob: one record
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(action_name, relative_path, source_guid)
)
```

Index: `idx_checkpoint_action ON checkpoint_output(action_name, relative_path)`

---

## The Disposition System

Every record that flows through the pipeline gets a disposition — a terminal label recording what happened to it. There are eight values:

```
Disposition        Meaning
─────────────────  ──────────────────────────────────────────────
SUCCESS            LLM returned valid output, written to target
FAILED             Something went wrong (provider error, parse error, prep error)
EXHAUSTED          Retried max times, provider never returned valid output
FILTERED           Guard evaluation said "don't process this record"
SKIPPED            Upstream action didn't produce output for this record
DEFERRED           Batch submitted but not yet completed (temporary)
PASSTHROUGH        Record passed through without LLM processing
UNPROCESSED        Cascade casualty — upstream failure prevented processing
```

### Disposition sets (behavioral groupings)

Three frozen sets partition dispositions by how the system treats them:

```
GATE_TERMINAL_DISPOSITIONS (not reprocessed on re-run):
  SUCCESS, FILTERED, SKIPPED, PASSTHROUGH, EXHAUSTED

  These records are "done" from the disposition gate's perspective.
  The gate carries them forward without reprocessing.

RUNNING_CLEAR_DISPOSITIONS (cleared when resuming an interrupted action):
  FAILED, EXHAUSTED, DEFERRED

  When a RUNNING action resumes, these dispositions are deleted so the
  records flow through again. SUCCESS, PASSTHROUGH, FILTERED, SKIPPED
  are preserved so checkpointed progress survives.

FAILURE_DISPOSITIONS (eligible for retry):
  FAILED, EXHAUSTED

  Only primary failures the user can act on. Excludes UNPROCESSED
  (cascade casualty — resolves when upstream is retried).
```

### DELETE-then-INSERT write semantics

The UNIQUE constraint on `record_disposition` is `(action_name, record_id, disposition)`, which means the same record could theoretically have rows for multiple dispositions (e.g., an old FAILED and a new SUCCESS). To prevent this coexistence, `set_disposition()` uses DELETE-then-INSERT:

```
1. DELETE FROM record_disposition
   WHERE action_name = ? AND record_id = ?

2. INSERT INTO record_disposition
   (action_name, record_id, disposition, ...)
   VALUES (?, ?, ?, ...)
```

This ensures each `(action_name, record_id)` pair has exactly one disposition row at any time. The batch variant `set_dispositions_batch()` uses the same pattern with `executemany`.

---

## NODE_LEVEL_RECORD_ID Sentinel

```python
NODE_LEVEL_RECORD_ID = "__node__"
```

Some signals apply to an entire action node, not to individual records. For example, when the entire action is deferred (batch submitted) or when a node-level failure occurs. The sentinel `__node__` is used as the `record_id` in these cases.

Methods like `get_failed_items()` and `has_successful_items()` explicitly filter out `__node__` rows so they only return item-level dispositions.

`get_terminal_record_ids()` also excludes `__node__` from its results — it returns only real record IDs with gate-terminal dispositions.

---

## Checkpoint System (Incremental Online Resume)

The checkpoint table enables crash recovery for the online (synchronous) processing path. During online processing, each successfully processed record is checkpointed immediately:

```
Processing record 1 → SUCCESS → save_checkpoint_records()
Processing record 2 → SUCCESS → save_checkpoint_records()
Processing record 3 → [CRASH]

On resume:
  read_checkpoint_records() → records 1 and 2
  Skip records 1 and 2 (already done)
  Resume from record 3
```

The flow:

1. **During processing**: `save_checkpoint_records()` upserts each batch of processed records using `INSERT OR REPLACE` keyed on `(action_name, relative_path, source_guid)`.
2. **On resume**: `read_checkpoint_records()` retrieves all checkpointed records for the action/path, ordered by insertion ID.
3. **After completion**: `clear_checkpoint_records()` deletes all checkpoint rows for the action. Checkpoint data is transient — it exists only between start and successful finish.

Unlike target_data (which stores all records as one JSON blob), checkpoint_output stores **one row per record** with `source_guid` as the dedup key. This allows incremental appending without rewriting the entire blob on each checkpoint.

---

## Thread Safety

The SQLite backend is designed for multi-threaded access within a single process:

```
┌──────────────────────────────────────────┐
│  SQLiteBackend                           │
│                                          │
│  self._lock = threading.RLock()          │
│    └─ Every public method acquires this  │
│       before touching self._connection   │
│                                          │
│  self._connection = sqlite3.connect(     │
│    check_same_thread=False,              │
│    timeout=30.0                          │  ← StorageDefaults.SQLITE_LOCK_TIMEOUT_SECONDS
│  )                                       │
│                                          │
│  PRAGMA journal_mode=WAL                 │
│    └─ Allows concurrent readers while    │
│       one writer holds the lock          │
│                                          │
│  PRAGMA foreign_keys=ON                  │
└──────────────────────────────────────────┘
```

The lock is an `RLock` (reentrant) because the `connection` property may be called from within code that already holds the lock. All write methods follow the pattern: acquire lock, execute, commit on success / rollback on failure, release lock. Read methods also hold the lock for the full execute-fetch pair to prevent interleaving.

---

## Schema Migration (_enforce_schema)

When the framework upgrades and adds columns to a table, existing databases need to be updated without losing data. `_enforce_schema()` runs at initialization, before `CREATE TABLE` statements:

```
For each table in _REQUIRED_COLUMNS:
  1. PRAGMA table_info(table_name) → get existing columns
  2. If table doesn't exist yet → skip (CREATE TABLE will handle it)
  3. Compute: missing = required_columns - existing_columns
  4. For each missing column:
       ALTER TABLE "table" ADD COLUMN "column" TEXT DEFAULT NULL
```

Key design decisions:
- **Never drops tables** — user data must survive framework upgrades.
- **Only adds columns** — does not remove or rename existing columns.
- **All new columns are TEXT DEFAULT NULL** — the most permissive type; application code handles typing.
- **Table names in `_REQUIRED_COLUMNS` are hardcoded** — not user input, but the implementation still quotes identifiers as defense-in-depth.

The `_REQUIRED_COLUMNS` dictionary lists the columns each table must have:

| Table | Required columns |
|-------|-----------------|
| `source_data` | relative_path, source_guid, data, created_at |
| `target_data` | action_name, relative_path, data, record_count, created_at |
| `record_disposition` | action_name, record_id, disposition, reason, relative_path, input_snapshot, detail, created_at |
| `prompt_trace` | action_name, record_id, attempt, compiled_prompt, llm_context, response_text, model_name, model_vendor, run_mode, prompt_length, context_length, response_length, created_at |

Note: `checkpoint_output` is not in `_REQUIRED_COLUMNS` because it was added after the migration system and has no legacy schemas to handle.

---

## Maintenance Operations

`perform_maintenance()` runs four idempotent cleanup operations after each workflow completes:

### 1. WAL checkpoint (`_checkpoint_wal`)

Runs `PRAGMA wal_checkpoint(TRUNCATE)` to flush the write-ahead log back into the main database file and reclaim disk space. Non-fatal on failure.

### 2. Stale disposition cleanup (`_cleanup_stale_dispositions`)

When a workflow re-runs, records that previously FAILED may now succeed. This operation finds records that have both a FAILED/EXHAUSTED disposition and a newer SUCCESS disposition (by `id` ordering), and deletes the old failure rows. Prevents stale failure data from accumulating.

### 3. Prompt trace retention (`_enforce_prompt_trace_retention`)

Keeps traces from the N most recent calendar days (default: 10, from `StorageDefaults.PROMPT_TRACE_RETENTION_RUNS`). Uses `DATE(created_at)` as the boundary — multiple runs on the same day count as one retention unit. Deletes all traces older than the Nth distinct date.

### 4. Source data TTL (`_enforce_source_data_ttl`)

Deletes `source_data` rows older than the configured TTL in days. Default is `None` (keep forever). Uses SQLite's `datetime('now', '-N days')` for the cutoff.

---

## Identifier Validation

All action names, relative paths, and record IDs pass through `_validate_identifier()` before being used in queries:

```
Allowed characters:  a-z A-Z 0-9 _ - . / (space)
Blocked:
  - Empty or whitespace-only strings
  - Path traversal ("..") as a path component
  - Backslashes (normalized to forward slashes)
  - Any character outside the allowlist
```

This is defense-in-depth. All SQL uses parameterized queries, so injection is not possible through values. The validation catches malformed identifiers early with clear error messages rather than letting them propagate to confusing SQL errors.

---

## File Index

| File | Role |
|------|------|
| `__init__.py` | Factory: `get_storage_backend(workflow_path, workflow_name, backend_type)` and `BACKENDS` registry |
| `backend.py` | Abstract base class: `StorageBackend`, disposition constants, `Disposition` enum, `NODE_LEVEL_RECORD_ID`, `FAILURE_DISPOSITIONS`, `RUNNING_CLEAR_DISPOSITIONS` |
| `backends/sqlite_backend.py` | SQLite implementation: all 5 tables, schema migration, maintenance, thread-safe CRUD |

---

## Caveats

1. **target_data uses a blob model.** The `data` column stores the entire `list[dict]` as one JSON string. This means `write_target()` replaces all records for an `(action_name, relative_path)` pair atomically. There is no way to update a single record within the blob without rewriting the whole thing. This is deliberate — the workflow writes complete output for a path in one shot.

2. **checkpoint_output uses a row-per-record model.** Unlike target_data, each checkpointed record gets its own row. This allows incremental appending via `INSERT OR REPLACE` without rewriting a blob. The two models serve different access patterns: target_data is write-once-read-many, checkpoint_output is append-during-processing-then-delete.

3. **DELETE-then-INSERT is not atomic at the SQL level.** If the process crashes between the DELETE and INSERT in `set_disposition()`, the disposition row is lost. This is acceptable because a missing disposition means the record will be reprocessed on the next run, which is the safe default.

4. **delete_target vs clear_disposition are independent.** `delete_target()` removes rows from `target_data` but does NOT touch `record_disposition`. `clear_disposition()` removes rows from `record_disposition` but does NOT touch `target_data`. Callers must call both if they want a clean reset. The `--fresh` flag in the workflow layer coordinates this.

5. **Schema migration only adds columns.** If a column is renamed or removed in a future version, `_enforce_schema()` will not handle it. The table will have both old and new columns. There is no `DROP COLUMN` or `ALTER COLUMN` path.

6. **input_snapshot truncation is lossy.** When `input_snapshot` exceeds 10KB, it is replaced with a JSON wrapper containing only the first 8KB. The original data is not recoverable from the truncated form.

7. **Prompt trace fields are capped at 1MB.** Any `compiled_prompt`, `llm_context`, or `response_text` exceeding `_MAX_TRACE_FIELD_SIZE` (1,048,576 bytes) is replaced with a truncation marker. The original lengths are preserved in `prompt_length`, `context_length`, and `response_length` columns (computed before truncation).

8. **WAL mode persists across connections.** Once `PRAGMA journal_mode=WAL` is set, it persists in the database file. Future connections inherit it regardless of whether they set it explicitly. This means the `.db-wal` and `.db-shm` files may exist even when no connection is open.

9. **Threading model is single-process only.** The `RLock` serializes access within one Python process. Multiple processes writing to the same database rely on SQLite's file-level locking (with the 30-second timeout). The framework does not currently use multi-process writes, but the lock timeout is the safety net if it ever does.

10. **get_terminal_record_ids imports from processing at call time.** The method does `from agent_actions.processing.disposition_gate import GATE_TERMINAL_DISPOSITIONS` inside the method body to avoid a circular import. This means the set of terminal dispositions is defined in the processing module, not in storage.

11. **source_data deduplication is by source_guid only within a path.** The UNIQUE constraint is `(relative_path, source_guid)`. The same `source_guid` can exist under different `relative_path` values without conflict. A record without a `source_guid` is an upstream invariant violation: `write_source` raises `DataValidationError` (fail-loud) rather than silently dropping it.

12. **read_target goes through a template method.** The public `read_target()` on `StorageBackend` calls `_read_target_raw()` (implemented by SQLiteBackend), then runs `validate_lifecycle_batch()` and `reset_for_downstream()`. This ensures lifecycle validation happens for every backend without each one reimplementing it.

13. **Maintenance operations are non-fatal.** All four maintenance operations (`_checkpoint_wal`, `_cleanup_stale_dispositions`, `_enforce_prompt_trace_retention`, `_enforce_source_data_ttl`) catch `sqlite3.Error` and log warnings instead of raising. A maintenance failure does not block workflow completion.

14. **The base class uses no-op defaults for optional methods.** `set_disposition()`, `write_prompt_trace()`, `save_checkpoint_records()`, and `clear_checkpoint_records()` are no-ops on `StorageBackend`. This means a backend that forgets to override them will silently drop data. The `# noqa: B027` comments acknowledge this intentional pattern.
