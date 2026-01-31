# RFC: Pluggable Storage Backend

**Status:** Draft
**Created:** 2026-01-30

---

## Summary

Add a simple storage abstraction using DuckDB as the default backend. Design makes adding new connectors (S3, GCS) easy later.

---

## Problem

Current storage is scattered JSON files:
```
agent_io/
├── source/{node}/batch_n.json
├── target/{action}/*.json
└── batch/
```

**Issues:**
- Can't query across runs
- No cleanup mechanism
- Hard to trace lineage
- Switching to cloud requires code changes

---

## Solution

### Simple Interface

```python
# agent_actions/storage/backend.py

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass


@dataclass
class RunInfo:
    run_id: str
    workflow_name: str
    started_at: datetime
    status: str
    actions: List[str]


class StorageBackend(ABC):
    """
    Base class for storage backends.

    To add a new backend:
    1. Subclass StorageBackend
    2. Implement abstract methods
    3. Register in BACKENDS dict
    """

    @abstractmethod
    def write_output(self, run_id: str, action_name: str, data: List[Dict], metadata: Optional[Dict] = None) -> str:
        """Write action output. Returns URI."""
        pass

    @abstractmethod
    def read_output(self, run_id: str, action_name: str) -> List[Dict]:
        """Read action output."""
        pass

    @abstractmethod
    def write_source(self, run_id: str, node_name: str, data: List[Dict]) -> str:
        """Write source data."""
        pass

    @abstractmethod
    def read_source(self, run_id: str, node_name: str) -> List[Dict]:
        """Read source data."""
        pass

    @abstractmethod
    def list_runs(self, workflow_name: Optional[str] = None, since: Optional[datetime] = None, limit: int = 50) -> List[RunInfo]:
        """List runs with filters."""
        pass

    @abstractmethod
    def get_run(self, run_id: str) -> Optional[RunInfo]:
        """Get run info."""
        pass

    @abstractmethod
    def delete_run(self, run_id: str) -> bool:
        """Delete a run."""
        pass

    @abstractmethod
    def cleanup(self, older_than: datetime) -> int:
        """Delete old runs. Returns count."""
        pass

    def initialize(self) -> None:
        """Called on first use."""
        pass

    def close(self) -> None:
        """Cleanup."""
        pass
```

### DuckDB Backend (Default)

```python
# agent_actions/storage/backends/duckdb_backend.py

import duckdb
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from agent_actions.storage.backend import StorageBackend, RunInfo


class DuckDBBackend(StorageBackend):
    """
    DuckDB storage backend.

    All data in a single .duckdb file with SQL queryability.

    Tables:
        runs: run_id, workflow_name, started_at, status
        outputs: run_id, action_name, data (JSON), created_at
        sources: run_id, node_name, data (JSON), created_at
    """

    def __init__(self, db_path: str = "./agent_io/workflows.duckdb"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            self._conn = duckdb.connect(str(self.db_path))
        return self._conn

    def initialize(self) -> None:
        """Create tables."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id VARCHAR PRIMARY KEY,
                workflow_name VARCHAR NOT NULL,
                started_at TIMESTAMP NOT NULL,
                status VARCHAR DEFAULT 'running'
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS outputs (
                id INTEGER PRIMARY KEY,
                run_id VARCHAR NOT NULL,
                action_name VARCHAR NOT NULL,
                data JSON NOT NULL,
                record_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY,
                run_id VARCHAR NOT NULL,
                node_name VARCHAR NOT NULL,
                data JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_outputs_run ON outputs(run_id, action_name)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_wf ON runs(workflow_name)")

    def write_output(self, run_id: str, action_name: str, data: List[Dict], metadata=None) -> str:
        self._ensure_run(run_id)
        self.conn.execute("DELETE FROM outputs WHERE run_id = ? AND action_name = ?", [run_id, action_name])
        self.conn.execute(
            "INSERT INTO outputs (run_id, action_name, data, record_count, created_at) VALUES (?, ?, ?, ?, ?)",
            [run_id, action_name, json.dumps(data), len(data), datetime.utcnow()]
        )
        return f"duckdb://{self.db_path}?run={run_id}&action={action_name}"

    def read_output(self, run_id: str, action_name: str) -> List[Dict]:
        result = self.conn.execute(
            "SELECT data FROM outputs WHERE run_id = ? AND action_name = ?",
            [run_id, action_name]
        ).fetchone()
        return json.loads(result[0]) if result else []

    def write_source(self, run_id: str, node_name: str, data: List[Dict]) -> str:
        self._ensure_run(run_id)
        # Dedup by source_guid
        existing = self.read_source(run_id, node_name)
        existing_guids = {r.get("source_guid") for r in existing}
        new_records = [r for r in data if r.get("source_guid") not in existing_guids]

        if new_records:
            all_data = existing + new_records
            self.conn.execute("DELETE FROM sources WHERE run_id = ? AND node_name = ?", [run_id, node_name])
            self.conn.execute(
                "INSERT INTO sources (run_id, node_name, data, created_at) VALUES (?, ?, ?, ?)",
                [run_id, node_name, json.dumps(all_data), datetime.utcnow()]
            )
        return f"duckdb://{self.db_path}?run={run_id}&source={node_name}"

    def read_source(self, run_id: str, node_name: str) -> List[Dict]:
        result = self.conn.execute(
            "SELECT data FROM sources WHERE run_id = ? AND node_name = ?",
            [run_id, node_name]
        ).fetchone()
        return json.loads(result[0]) if result else []

    def list_runs(self, workflow_name=None, since=None, limit=50) -> List[RunInfo]:
        query = "SELECT run_id, workflow_name, started_at, status FROM runs WHERE 1=1"
        params = []
        if workflow_name:
            query += " AND workflow_name = ?"
            params.append(workflow_name)
        if since:
            query += " AND started_at >= ?"
            params.append(since)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        runs = []
        for row in self.conn.execute(query, params).fetchall():
            actions = [a[0] for a in self.conn.execute(
                "SELECT DISTINCT action_name FROM outputs WHERE run_id = ?", [row[0]]
            ).fetchall()]
            runs.append(RunInfo(row[0], row[1], row[2], row[3], actions))
        return runs

    def get_run(self, run_id: str) -> Optional[RunInfo]:
        row = self.conn.execute(
            "SELECT run_id, workflow_name, started_at, status FROM runs WHERE run_id = ?",
            [run_id]
        ).fetchone()
        if not row:
            return None
        actions = [a[0] for a in self.conn.execute(
            "SELECT DISTINCT action_name FROM outputs WHERE run_id = ?", [run_id]
        ).fetchall()]
        return RunInfo(row[0], row[1], row[2], row[3], actions)

    def delete_run(self, run_id: str) -> bool:
        if not self.get_run(run_id):
            return False
        self.conn.execute("DELETE FROM outputs WHERE run_id = ?", [run_id])
        self.conn.execute("DELETE FROM sources WHERE run_id = ?", [run_id])
        self.conn.execute("DELETE FROM runs WHERE run_id = ?", [run_id])
        return True

    def cleanup(self, older_than: datetime) -> int:
        old = self.conn.execute("SELECT run_id FROM runs WHERE started_at < ?", [older_than]).fetchall()
        for (run_id,) in old:
            self.delete_run(run_id)
        return len(old)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_run(self, run_id: str, workflow_name: str = "unknown"):
        if not self.conn.execute("SELECT 1 FROM runs WHERE run_id = ?", [run_id]).fetchone():
            self.conn.execute(
                "INSERT INTO runs (run_id, workflow_name, started_at) VALUES (?, ?, ?)",
                [run_id, workflow_name, datetime.utcnow()]
            )

    def query(self, sql: str, params=None) -> List[Dict]:
        """Run arbitrary SQL."""
        result = self.conn.execute(sql, params or [])
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row)) for row in result.fetchall()]
```

### Factory

```python
# agent_actions/storage/__init__.py

from typing import Dict, Type, Optional
from agent_actions.storage.backend import StorageBackend
from agent_actions.storage.backends.duckdb_backend import DuckDBBackend

BACKENDS: Dict[str, Type[StorageBackend]] = {
    "duckdb": DuckDBBackend,
}

_default: Optional[StorageBackend] = None


def get_storage(backend_type: str = "duckdb", **config) -> StorageBackend:
    """Get storage backend."""
    if backend_type not in BACKENDS:
        raise ValueError(f"Unknown backend: {backend_type}. Available: {list(BACKENDS.keys())}")
    backend = BACKENDS[backend_type](**config)
    backend.initialize()
    return backend


def get_default_storage() -> StorageBackend:
    """Get default backend (singleton)."""
    global _default
    if _default is None:
        _default = get_storage("duckdb")
    return _default


def register_backend(name: str, cls: Type[StorageBackend]) -> None:
    """Register custom backend."""
    BACKENDS[name] = cls
```

---

## CLI Commands

```python
# agent_actions/cli/commands/storage.py

import click
from datetime import datetime, timedelta
from agent_actions.storage import get_default_storage


@click.group(name="storage")
def storage():
    """Storage management."""
    pass


@storage.command(name="list")
@click.option("--workflow", "-w", help="Filter by workflow")
@click.option("--since", "-s", help="Since (e.g., 7d, 24h)")
@click.option("--limit", "-n", default=20)
def list_runs(workflow, since, limit):
    """List runs."""
    backend = get_default_storage()
    since_dt = datetime.utcnow() - _parse_duration(since) if since else None
    runs = backend.list_runs(workflow, since_dt, limit)

    if not runs:
        click.echo("No runs found")
        return

    click.echo(f"{'Run ID':<36} {'Workflow':<20} {'Started':<16} {'Actions'}")
    click.echo("-" * 80)
    for r in runs:
        click.echo(f"{r.run_id:<36} {r.workflow_name:<20} {r.started_at:%Y-%m-%d %H:%M} {len(r.actions)}")


@storage.command(name="show")
@click.argument("run_id")
def show_run(run_id):
    """Show run details."""
    backend = get_default_storage()
    run = backend.get_run(run_id)
    if not run:
        click.echo(f"Not found: {run_id}")
        return
    click.echo(f"Run: {run.run_id}")
    click.echo(f"Workflow: {run.workflow_name}")
    click.echo(f"Started: {run.started_at}")
    click.echo(f"Status: {run.status}")
    click.echo(f"Actions: {', '.join(run.actions)}")


@storage.command(name="delete")
@click.argument("run_id")
@click.confirmation_option(prompt="Delete?")
def delete_run(run_id):
    """Delete a run."""
    if get_default_storage().delete_run(run_id):
        click.echo(f"Deleted: {run_id}")
    else:
        click.echo(f"Not found: {run_id}")


@storage.command(name="cleanup")
@click.option("--older-than", required=True, help="e.g., 30d")
@click.option("--dry-run", is_flag=True)
def cleanup(older_than, dry_run):
    """Delete old runs."""
    backend = get_default_storage()
    cutoff = datetime.utcnow() - _parse_duration(older_than)

    if dry_run:
        runs = [r for r in backend.list_runs(limit=1000) if r.started_at < cutoff]
        click.echo(f"Would delete {len(runs)} runs")
    else:
        count = backend.cleanup(cutoff)
        click.echo(f"Deleted {count} runs")


@storage.command(name="query")
@click.argument("sql")
def run_query(sql):
    """Run SQL query (DuckDB only)."""
    backend = get_default_storage()
    if not hasattr(backend, 'query'):
        click.echo("Query not supported")
        return
    results = backend.query(sql)
    if results:
        headers = list(results[0].keys())
        click.echo(" | ".join(headers))
        for row in results[:50]:
            click.echo(" | ".join(str(row.get(h, ""))[:25] for h in headers))


def _parse_duration(s: str) -> timedelta:
    s = s.lower()
    if s.endswith('d'): return timedelta(days=int(s[:-1]))
    if s.endswith('h'): return timedelta(hours=int(s[:-1]))
    if s.endswith('m'): return timedelta(minutes=int(s[:-1]))
    return timedelta(days=int(s))
```

---

## Adding New Backends

Example S3 backend:

```python
# agent_actions/storage/backends/s3_backend.py

import json
import boto3
from agent_actions.storage.backend import StorageBackend, RunInfo

class S3Backend(StorageBackend):
    def __init__(self, bucket: str, prefix: str = "workflows/"):
        self.bucket = bucket
        self.prefix = prefix
        self.s3 = boto3.client("s3")

    def write_output(self, run_id, action_name, data, metadata=None):
        key = f"{self.prefix}{run_id}/outputs/{action_name}.json"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=json.dumps(data))
        return f"s3://{self.bucket}/{key}"

    # ... implement other methods
```

Register:
```python
from agent_actions.storage import register_backend
from agent_actions.storage.backends.s3_backend import S3Backend
register_backend("s3", S3Backend)
```

---

## Files to Create

```
agent_actions/storage/
├── __init__.py
├── backend.py
└── backends/
    ├── __init__.py
    └── duckdb_backend.py

agent_actions/cli/commands/storage.py
```

---

## Usage

```bash
# List runs
agac storage list --since 7d

# Show run
agac storage show run_abc123

# Query
agac storage query "SELECT workflow_name, COUNT(*) FROM runs GROUP BY workflow_name"

# Cleanup
agac storage cleanup --older-than 30d
```

```python
from agent_actions.storage import get_storage

storage = get_storage()  # DuckDB default
storage.write_output(run_id, "action", data)
```

---

**End of RFC**
