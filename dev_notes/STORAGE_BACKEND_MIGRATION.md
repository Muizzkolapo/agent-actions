# Storage Backend Migration Guide

This guide covers migrating existing workflows from JSON file storage to the new SQLite backend.

## Overview

The pluggable storage backend system replaces the previous JSON file-based storage for source and target data. Benefits include:

- **Better query performance** - SQLite indexes enable fast lookups
- **Data integrity** - ACID transactions prevent partial writes
- **Deduplication** - Built-in source_guid deduplication
- **Concurrency** - WAL mode allows concurrent reads
- **Extensibility** - Abstract interface supports future backends (S3, DuckDB)

## What Changes

### Storage Location

| Data Type | Old Location | New Location |
|-----------|--------------|--------------|
| Target data | `agent_io/target/{node}/*.json` | `agent_io/{workflow}.db` (target_data table) |
| Source data | `agent_io/source_data/*.json` | `agent_io/{workflow}.db` (source_data table) |
| Seed data | `seed_data/*.json` | Unchanged |
| Staging data | `agent_io/staging/*.json` | Unchanged |

### File Structure

**Before:**
```
my_workflow/
├── seed_data/
│   └── input.json
├── agent_io/
│   ├── staging/
│   │   └── staging.json
│   ├── source_data/
│   │   └── batch_001.json
│   └── target/
│       ├── extract/
│       │   └── batch_001.json
│       └── transform/
│           └── batch_001.json
└── agent_config/
    └── agents.yaml
```

**After:**
```
my_workflow/
├── seed_data/
│   └── input.json
├── agent_io/
│   ├── staging/
│   │   └── staging.json
│   └── my_workflow.db    # <-- All source + target data
└── agent_config/
    └── agents.yaml
```

## Migration Steps

### Step 1: Backup Existing Data

Before migrating, backup your existing JSON files:

```bash
cd /path/to/your/workflow
cp -r agent_io agent_io_backup
```

### Step 2: Run Migration Script

Use the provided migration script to convert existing JSON files to SQLite:

```bash
agent-actions migrate-storage /path/to/workflow
```

Or run manually with Python:

```python
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from pathlib import Path
import json

workflow_path = Path("/path/to/workflow")
workflow_name = workflow_path.name
db_path = workflow_path / "agent_io" / f"{workflow_name}.db"

backend = SQLiteBackend(str(db_path), workflow_name)
backend.initialize()

# Migrate target data
target_dir = workflow_path / "agent_io" / "target"
for node_dir in target_dir.iterdir():
    if node_dir.is_dir():
        action_name = node_dir.name
        for json_file in node_dir.glob("*.json"):
            with open(json_file) as f:
                data = json.load(f)
            relative_path = json_file.name
            backend.write_target(action_name, relative_path, data)
            print(f"Migrated target: {action_name}/{relative_path}")

# Migrate source data
source_dir = workflow_path / "agent_io" / "source_data"
if source_dir.exists():
    for json_file in source_dir.glob("*.json"):
        with open(json_file) as f:
            data = json.load(f)
        relative_path = json_file.name
        backend.write_source(relative_path, data, enable_deduplication=False)
        print(f"Migrated source: {relative_path}")

backend.close()
print(f"Migration complete: {db_path}")
```

### Step 3: Verify Migration

Query the database to verify data was migrated correctly:

```bash
sqlite3 /path/to/workflow/agent_io/workflow.db

-- Check target data
SELECT action_name, relative_path, record_count FROM target_data;

-- Check source data count
SELECT relative_path, COUNT(*) as records FROM source_data GROUP BY relative_path;

-- Preview actual data
SELECT data FROM target_data WHERE action_name = 'extract' LIMIT 1;
```

### Step 4: Clean Up Old Files (Optional)

Once verified, you can remove the old JSON directories:

```bash
rm -rf agent_io/target
rm -rf agent_io/source_data
```

## Querying Data

### Using SQLite CLI

```bash
sqlite3 /path/to/workflow/agent_io/workflow.db
```

Common queries:

```sql
-- List all nodes
SELECT DISTINCT action_name FROM target_data;

-- Count records per node
SELECT action_name, SUM(record_count) as total FROM target_data GROUP BY action_name;

-- Get records for a specific node/file
SELECT json_extract(data, '$[0].content') FROM target_data
WHERE action_name = 'extract' AND relative_path = 'batch_001.json';

-- Search within JSON data
SELECT * FROM target_data
WHERE json_extract(data, '$[0].source_guid') = 'specific-guid';
```

### Using Python

```python
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

backend = SQLiteBackend("/path/to/workflow.db", "workflow_name")
backend.initialize()

# Read target data
data = backend.read_target("extract", "batch_001.json")

# List files for a node
files = backend.list_target_files("extract")

# Preview with pagination
preview = backend.preview_target("extract", limit=10, offset=0)

# Get statistics
stats = backend.get_storage_stats()
print(f"Total records: {stats['target_count']}")
print(f"Database size: {stats['db_size_human']}")

backend.close()
```

### Using VS Code Extension

The VS Code extension provides a "Preview Data" option in the workflow tree view:

1. Expand an action in the Workflow Navigator
2. Click "Preview Data" to open the data preview panel
3. Use pagination controls to browse records

## Database Schema

### source_data Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-incrementing primary key |
| relative_path | TEXT | Original file path (e.g., "batch_001.json") |
| source_guid | TEXT | Unique identifier for deduplication |
| data | TEXT | JSON-encoded record |
| created_at | TEXT | Timestamp of insertion |

**Unique constraint:** (relative_path, source_guid)

### target_data Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-incrementing primary key |
| action_name | TEXT | Action/node name (e.g., "extract") |
| relative_path | TEXT | Original file path (e.g., "batch_001.json") |
| data | TEXT | JSON-encoded array of records |
| record_count | INTEGER | Number of records in data array |
| created_at | TEXT | Timestamp of insertion |

**Unique constraint:** (action_name, relative_path)

## Troubleshooting

### Database Locked

If you see "database is locked" errors:

1. Ensure only one process writes at a time
2. The backend uses WAL mode for better concurrency
3. Check for hanging processes: `lsof workflow.db`

### Missing Data After Migration

1. Verify the old JSON files exist in backup
2. Check migration logs for errors
3. Re-run migration with `enable_deduplication=False`

### Performance Issues

For large databases:

```sql
-- Analyze tables for query optimization
ANALYZE;

-- Check index usage
EXPLAIN QUERY PLAN SELECT * FROM target_data WHERE action_name = 'extract';
```

## Rollback

To rollback to JSON storage:

1. Restore from backup: `cp -r agent_io_backup/* agent_io/`
2. Remove the database: `rm agent_io/*.db`

## Future Backends

The storage backend interface is designed for extensibility. Planned backends:

- **DuckDB** - Columnar storage for analytics workloads
- **S3** - Cloud storage for distributed workflows
- **PostgreSQL** - Shared database for team workflows

To implement a custom backend, extend `StorageBackend` from `agent_actions.storage.backend`:

```python
from agent_actions.storage.backend import StorageBackend

class MyCustomBackend(StorageBackend):
    @property
    def backend_type(self) -> str:
        return "custom"

    def initialize(self) -> None:
        # Setup storage
        pass

    def write_target(self, action_name, relative_path, data):
        # Write implementation
        pass

    # ... implement other abstract methods
```
