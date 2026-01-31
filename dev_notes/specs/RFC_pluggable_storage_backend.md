# RFC: Pluggable Storage Backend Abstraction

**Status:** Draft
**Created:** 2026-01-30
**Author:** System Architecture
**Related:** RFC_unified_processing_architecture.md, RFC_multiple_dependencies_primary_input.md

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Problem Statement](#problem-statement)
3. [Proposed Solution](#proposed-solution)
4. [Configuration Schema](#configuration-schema)
5. [Interface Design](#interface-design)
6. [Backend Implementations](#backend-implementations)
7. [URI-Based Data References](#uri-based-data-references)
8. [Caching Layer](#caching-layer)
9. [CLI Commands](#cli-commands)
10. [Lineage Tracking](#lineage-tracking)
11. [Migration Path](#migration-path)
12. [Testing Strategy](#testing-strategy)
13. [Backward Compatibility](#backward-compatibility)
14. [Examples](#examples)
15. [Open Questions](#open-questions)

---

## Executive Summary

This RFC proposes a storage abstraction layer for agent-actions that decouples workflow logic from data persistence. The abstraction enables seamless switching between local files, databases, and cloud object stores without changing workflow definitions.

### Key Changes

1. **Storage Backend Interface**: Abstract `IStorageBackend` interface with pluggable implementations
2. **Configuration-Driven Backend Selection**: YAML-based storage configuration in workflow defaults
3. **Environment-Based Configuration**: Support for different storage configs per environment (dev/staging/prod)
4. **Lineage Tracking**: Automatic data provenance tracking integrated into storage layer
5. **CLI Management Commands**: New `agac storage` command group for data management

---

## Problem Statement

### Current Architecture

The current agent-actions system uses hardcoded file-based storage patterns:

```
{workflow_name}/
├── agent_config/           # YAML workflow definitions
│   └── {action}.yml
└── agent_io/               # All I/O operations
    ├── source/             # Raw input data with source_guid tracking
    │   └── {node_name}/batch_{n}.json
    ├── target/             # Agent output results
    │   └── {agent_name}/{output_files}.json
    ├── batch/              # Batch job submissions and status
    └── side_output/        # Secondary outputs
```

**Key Storage Components:**

| Component | File | Responsibility |
|-----------|------|----------------|
| `FileWriter` | `agent_actions/output/writer.py` | Write staging/target/source files |
| `UnifiedSourceDataSaver` | `agent_actions/output/saver.py` | Source data with deduplication & locking |
| `PathManager` | `agent_actions/config/paths.py` | Centralized path resolution |
| `BaseLoader` | `agent_actions/input/loaders/base.py` | File loading with retry logic |

### Limitations

| Issue | Impact | Current Code Location |
|-------|--------|----------------------|
| **File I/O overhead** | Slow at scale with large datasets | `FileWriter.write_target()` |
| **No cloud support** | Can't run workflows in cloud environments | All storage is local file-based |
| **No queryability** | Can't search across runs or actions | No indexing or metadata storage |
| **No retention policy** | Disk fills up with old runs | No TTL or cleanup mechanism |
| **Tight coupling** | Switching storage requires code changes | `PathManager` hardcodes `agent_io/` structure |
| **Limited lineage** | Hard to trace data provenance across runs | Lineage in individual records, not centralized |

### User Stories

1. **Cloud Deployment**: "As a DevOps engineer, I want to deploy agent-actions workflows to GCP/AWS without modifying workflow definitions."

2. **Data Retention**: "As a data engineer, I want automatic cleanup of old workflow runs to manage storage costs."

3. **Audit Trail**: "As a compliance officer, I want to query all workflow runs that produced a specific output for auditing."

4. **Multi-Environment**: "As a developer, I want to use local files for development but cloud storage for production."

5. **Large Datasets**: "As a data scientist, I want to process datasets that don't fit in memory using streaming/chunked storage."

---

## Proposed Solution

### Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Workflow Execution Layer                            │
│  AgentWorkflow → AgentExecutor → AgentRunner → ProcessingPipeline            │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            Storage Abstraction Layer                          │
│                                                                               │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐          │
│  │  StorageManager │────│ IStorageBackend │────│    URIResolver  │          │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘          │
│           │                      │                      │                    │
│           │        ┌─────────────┴─────────────┐        │                    │
│           │        │                           │        │                    │
│           ▼        ▼                           ▼        ▼                    │
│  ┌────────────┐  ┌────────────┐    ┌────────────┐  ┌────────────┐           │
│  │   Cache    │  │LocalStorage│    │ GCSStorage │  │ S3Storage  │           │
│  │   Layer    │  │ (default)  │    │            │  │            │           │
│  └────────────┘  └────────────┘    └────────────┘  └────────────┘           │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Physical Storage Layer                              │
│  Local Filesystem  │  SQLite/DuckDB  │  GCS Buckets  │  S3 Buckets          │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Core Principles

1. **Interface-First Design**: All backends implement `IStorageBackend` interface
2. **Configuration-Driven**: Storage backend selected via YAML configuration
3. **Location-Agnostic**: Data referenced by URI, not file paths
4. **Fail-Fast Validation**: Invalid configuration errors at load time (consistent with RFC_unified_processing_architecture.md)
5. **Async/Sync Duality**: All operations support both modes (consistent with existing patterns)

---

## Configuration Schema

### Storage Configuration Block

Add a `storage` block to workflow defaults:

```yaml
defaults:
  storage:
    backend: local  # local | sqlite | gcs | s3 | azure

    config:
      # Local filesystem (current behavior - default)
      local:
        base_path: ./agent_io

      # SQLite/DuckDB for queryable local storage
      sqlite:
        path: ./workflows.db
        table_prefix: agac_

      # Google Cloud Storage
      gcs:
        bucket: my-ml-workflows
        prefix: workflows/{workflow_name}/
        project: ${GCP_PROJECT_ID}
        credentials: ${GOOGLE_APPLICATION_CREDENTIALS}

      # AWS S3
      s3:
        bucket: my-ml-workflows
        prefix: workflows/
        region: us-east-1
        endpoint: null  # For S3-compatible (MinIO, etc.)
        credentials:
          access_key_id: ${AWS_ACCESS_KEY_ID}
          secret_access_key: ${AWS_SECRET_ACCESS_KEY}

      # Azure Blob Storage
      azure:
        container: ml-workflows
        account_name: ${AZURE_STORAGE_ACCOUNT}
        credentials: ${AZURE_STORAGE_KEY}

    # Common options (apply to all backends)
    options:
      format: json          # json | parquet | arrow
      compression: none     # none | gzip | zstd | snappy
      keep_intermediate: true
      ttl: 7d               # Auto-cleanup after 7 days (null = never)
      versioning: true      # Keep history of overwrites
      lineage_tracking: true
```

### Environment-Based Configuration

Support environment-specific storage configurations:

```
config/
├── storage.local.yml      # Development (default)
├── storage.staging.yml    # Staging environment
└── storage.prod.yml       # Production environment
```

**storage.local.yml:**
```yaml
storage:
  backend: local
  config:
    local:
      base_path: ./agent_io
  options:
    format: json
    compression: none
    ttl: null  # No auto-cleanup in dev
```

**storage.prod.yml:**
```yaml
storage:
  backend: gcs
  config:
    gcs:
      bucket: prod-ml-workflows
      prefix: v1/
      project: ${GCP_PROJECT_ID}
  options:
    format: parquet
    compression: zstd
    ttl: 90d
    versioning: true
```

**Usage:**
```bash
# Development (default)
agac run -a my_workflow

# Production
agac run -a my_workflow --env prod
# or
AGENT_ACTIONS_ENV=prod agac run -a my_workflow
```

### Configuration Resolution Order

1. Command-line `--storage-config` flag (highest priority)
2. Environment variable `AGENT_ACTIONS_STORAGE_CONFIG`
3. Environment-specific file `config/storage.{env}.yml`
4. Workflow-level `defaults.storage` block
5. Project-level `agent_actions.yml` storage section
6. Built-in defaults (local filesystem)

---

## Interface Design

### Core Types

```python
# agent_actions/storage/types.py

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from enum import Enum
from datetime import datetime


class StorageBackendType(Enum):
    """Supported storage backend types."""
    LOCAL = "local"
    SQLITE = "sqlite"
    GCS = "gcs"
    S3 = "s3"
    AZURE = "azure"


class StorageFormat(Enum):
    """Supported data formats."""
    JSON = "json"
    PARQUET = "parquet"
    ARROW = "arrow"


class CompressionType(Enum):
    """Supported compression types."""
    NONE = "none"
    GZIP = "gzip"
    ZSTD = "zstd"
    SNAPPY = "snappy"


@dataclass
class StorageOptions:
    """Common storage options."""
    format: StorageFormat = StorageFormat.JSON
    compression: CompressionType = CompressionType.NONE
    keep_intermediate: bool = True
    ttl: Optional[str] = None  # e.g., "7d", "24h", None
    versioning: bool = False
    lineage_tracking: bool = True


@dataclass
class StorageConfig:
    """Storage configuration."""
    backend: StorageBackendType
    config: Dict[str, Any]
    options: StorageOptions = field(default_factory=StorageOptions)

    @classmethod
    def from_dict(cls, data: Dict) -> "StorageConfig":
        """Create StorageConfig from dictionary (YAML parsed)."""
        backend = StorageBackendType(data.get("backend", "local"))
        options = StorageOptions(
            format=StorageFormat(data.get("options", {}).get("format", "json")),
            compression=CompressionType(data.get("options", {}).get("compression", "none")),
            keep_intermediate=data.get("options", {}).get("keep_intermediate", True),
            ttl=data.get("options", {}).get("ttl"),
            versioning=data.get("options", {}).get("versioning", False),
            lineage_tracking=data.get("options", {}).get("lineage_tracking", True),
        )
        return cls(
            backend=backend,
            config=data.get("config", {}),
            options=options,
        )


@dataclass
class StorageMetadata:
    """Metadata associated with stored data."""
    run_id: str
    workflow_name: str
    action_name: str
    timestamp: datetime
    record_count: int
    format: StorageFormat
    compression: CompressionType
    schema_version: str
    agent_actions_version: str
    lineage: Optional[Dict[str, Any]] = None
    custom: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StorageLocation:
    """Represents a storage location (URI-based)."""
    uri: str
    backend: StorageBackendType
    metadata: Optional[StorageMetadata] = None

    @property
    def scheme(self) -> str:
        """Extract URI scheme (file, gs, s3, sqlite, etc.)."""
        return self.uri.split("://")[0] if "://" in self.uri else "file"


@dataclass
class ListRunsFilter:
    """Filter options for listing runs."""
    workflow_name: Optional[str] = None
    action_name: Optional[str] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    status: Optional[str] = None
    limit: int = 100
    offset: int = 0
```

### IStorageBackend Interface

```python
# agent_actions/storage/interfaces.py

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, AsyncIterator, Iterator
from datetime import datetime

from agent_actions.config.interfaces import IAsyncCapable, ProcessingMode
from agent_actions.storage.types import (
    StorageConfig,
    StorageMetadata,
    StorageLocation,
    ListRunsFilter,
)


class IStorageBackend(IAsyncCapable, ABC):
    """
    Abstract interface for storage backends.

    All storage backends implement this interface, enabling seamless
    switching between local files, databases, and cloud object stores.

    Design Principles:
    - Async/sync duality (consistent with existing IDataLoader pattern)
    - URI-based addressing for location-agnostic references
    - Fail-fast validation (consistent with RFC_unified_processing_architecture.md)
    - Progressive data exposure (only load what's needed)
    """

    @abstractmethod
    def __init__(self, config: StorageConfig) -> None:
        """Initialize backend with configuration."""
        pass

    # =========================================================================
    # Write Operations
    # =========================================================================

    @abstractmethod
    def write_output(
        self,
        run_id: str,
        action_name: str,
        data: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StorageLocation:
        """
        Write action output data.

        Args:
            run_id: Unique identifier for the workflow run
            action_name: Name of the action producing output
            data: List of output records
            metadata: Optional metadata to associate with output

        Returns:
            StorageLocation with URI of written data

        Raises:
            StorageWriteError: If write fails
        """
        pass

    async def write_output_async(
        self,
        run_id: str,
        action_name: str,
        data: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StorageLocation:
        """Async version of write_output."""
        import asyncio
        return await asyncio.to_thread(
            self.write_output, run_id, action_name, data, metadata
        )

    @abstractmethod
    def write_source(
        self,
        run_id: str,
        node_name: str,
        data: List[Dict[str, Any]],
        enable_dedup: bool = True,
    ) -> StorageLocation:
        """
        Write source data with optional deduplication.

        Args:
            run_id: Unique identifier for the workflow run
            node_name: Name of the source node
            data: List of source records with source_guid
            enable_dedup: Whether to deduplicate by source_guid

        Returns:
            StorageLocation with URI of written data
        """
        pass

    async def write_source_async(
        self,
        run_id: str,
        node_name: str,
        data: List[Dict[str, Any]],
        enable_dedup: bool = True,
    ) -> StorageLocation:
        """Async version of write_source."""
        import asyncio
        return await asyncio.to_thread(
            self.write_source, run_id, node_name, data, enable_dedup
        )

    # =========================================================================
    # Read Operations
    # =========================================================================

    @abstractmethod
    def read_output(
        self,
        run_id: str,
        action_name: str,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Read action output data.

        Args:
            run_id: Unique identifier for the workflow run
            action_name: Name of the action
            fields: Optional list of fields to load (progressive data exposure)

        Returns:
            List of output records

        Raises:
            StorageReadError: If read fails
            DataNotFoundError: If data doesn't exist
        """
        pass

    async def read_output_async(
        self,
        run_id: str,
        action_name: str,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Async version of read_output."""
        import asyncio
        return await asyncio.to_thread(
            self.read_output, run_id, action_name, fields
        )

    @abstractmethod
    def read_source(
        self,
        run_id: str,
        node_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Read source data.

        Args:
            run_id: Unique identifier for the workflow run
            node_name: Name of the source node

        Returns:
            List of source records
        """
        pass

    async def read_source_async(
        self,
        run_id: str,
        node_name: str,
    ) -> List[Dict[str, Any]]:
        """Async version of read_source."""
        import asyncio
        return await asyncio.to_thread(self.read_source, run_id, node_name)

    @abstractmethod
    def read_by_uri(self, uri: str) -> List[Dict[str, Any]]:
        """
        Read data by URI (location-agnostic).

        Args:
            uri: Storage URI (e.g., "file://./agent_io/target/...",
                 "gs://bucket/path/...", "sqlite://./db?...")

        Returns:
            List of records
        """
        pass

    async def read_by_uri_async(self, uri: str) -> List[Dict[str, Any]]:
        """Async version of read_by_uri."""
        import asyncio
        return await asyncio.to_thread(self.read_by_uri, uri)

    # =========================================================================
    # Streaming Operations (for large datasets)
    # =========================================================================

    def stream_output(
        self,
        run_id: str,
        action_name: str,
        batch_size: int = 1000,
    ) -> Iterator[List[Dict[str, Any]]]:
        """
        Stream action output in batches.

        Args:
            run_id: Unique identifier for the workflow run
            action_name: Name of the action
            batch_size: Number of records per batch

        Yields:
            Batches of output records
        """
        # Default implementation: read all and yield in batches
        data = self.read_output(run_id, action_name)
        for i in range(0, len(data), batch_size):
            yield data[i:i + batch_size]

    async def stream_output_async(
        self,
        run_id: str,
        action_name: str,
        batch_size: int = 1000,
    ) -> AsyncIterator[List[Dict[str, Any]]]:
        """Async streaming version."""
        data = await self.read_output_async(run_id, action_name)
        for i in range(0, len(data), batch_size):
            yield data[i:i + batch_size]

    # =========================================================================
    # Query Operations
    # =========================================================================

    @abstractmethod
    def list_runs(
        self,
        filters: Optional[ListRunsFilter] = None,
    ) -> List[Dict[str, Any]]:
        """
        List workflow runs with optional filters.

        Args:
            filters: Optional filters (workflow_name, since, status, etc.)

        Returns:
            List of run metadata dictionaries
        """
        pass

    async def list_runs_async(
        self,
        filters: Optional[ListRunsFilter] = None,
    ) -> List[Dict[str, Any]]:
        """Async version of list_runs."""
        import asyncio
        return await asyncio.to_thread(self.list_runs, filters)

    @abstractmethod
    def get_run_metadata(self, run_id: str) -> Dict[str, Any]:
        """
        Get metadata for a specific run.

        Args:
            run_id: Unique identifier for the workflow run

        Returns:
            Run metadata dictionary
        """
        pass

    async def get_run_metadata_async(self, run_id: str) -> Dict[str, Any]:
        """Async version of get_run_metadata."""
        import asyncio
        return await asyncio.to_thread(self.get_run_metadata, run_id)

    @abstractmethod
    def list_actions(self, run_id: str) -> List[str]:
        """
        List all actions in a run.

        Args:
            run_id: Unique identifier for the workflow run

        Returns:
            List of action names
        """
        pass

    # =========================================================================
    # Delete Operations
    # =========================================================================

    @abstractmethod
    def delete_run(self, run_id: str) -> bool:
        """
        Delete all data for a run.

        Args:
            run_id: Unique identifier for the workflow run

        Returns:
            True if deleted, False if not found
        """
        pass

    async def delete_run_async(self, run_id: str) -> bool:
        """Async version of delete_run."""
        import asyncio
        return await asyncio.to_thread(self.delete_run, run_id)

    @abstractmethod
    def cleanup(
        self,
        older_than: datetime,
        dry_run: bool = False,
    ) -> int:
        """
        Delete runs older than specified date.

        Args:
            older_than: Delete runs before this date
            dry_run: If True, only report what would be deleted

        Returns:
            Number of runs deleted (or would be deleted if dry_run)
        """
        pass

    async def cleanup_async(
        self,
        older_than: datetime,
        dry_run: bool = False,
    ) -> int:
        """Async version of cleanup."""
        import asyncio
        return await asyncio.to_thread(self.cleanup, older_than, dry_run)

    # =========================================================================
    # Lineage Operations
    # =========================================================================

    @abstractmethod
    def get_lineage(
        self,
        run_id: str,
        action_name: str,
    ) -> Dict[str, Any]:
        """
        Get lineage information for an action's output.

        Args:
            run_id: Unique identifier for the workflow run
            action_name: Name of the action

        Returns:
            Lineage dictionary with inputs, timestamps, etc.
        """
        pass

    @abstractmethod
    def get_downstream_lineage(
        self,
        run_id: str,
        action_name: str,
        depth: int = -1,
    ) -> List[Dict[str, Any]]:
        """
        Get all downstream actions that consumed this action's output.

        Args:
            run_id: Unique identifier for the workflow run
            action_name: Name of the action
            depth: How many levels downstream (-1 = all)

        Returns:
            List of downstream action lineage records
        """
        pass

    # =========================================================================
    # Utility Methods
    # =========================================================================

    @abstractmethod
    def exists(self, run_id: str, action_name: Optional[str] = None) -> bool:
        """
        Check if data exists.

        Args:
            run_id: Unique identifier for the workflow run
            action_name: Optional action name (if None, checks run exists)

        Returns:
            True if exists
        """
        pass

    @abstractmethod
    def get_uri(self, run_id: str, action_name: str) -> str:
        """
        Get URI for action output without reading data.

        Args:
            run_id: Unique identifier for the workflow run
            action_name: Name of the action

        Returns:
            Storage URI string
        """
        pass

    def supports_async(self) -> bool:
        """Return True if this backend supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return the preferred processing mode for this backend."""
        return ProcessingMode.AUTO
```

### StorageManager

```python
# agent_actions/storage/manager.py

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from agent_actions.storage.interfaces import IStorageBackend
from agent_actions.storage.types import (
    StorageConfig,
    StorageBackendType,
    StorageLocation,
    ListRunsFilter,
)
from agent_actions.storage.backends import (
    LocalStorage,
    SQLiteStorage,
    GCSStorage,
    S3Storage,
    AzureStorage,
)
from agent_actions.storage.cache import StorageCache
from agent_actions.errors import ConfigurationError, StorageError

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Central manager for storage operations.

    Handles backend instantiation, caching, and provides unified
    interface for all storage operations.
    """

    BACKEND_REGISTRY: Dict[StorageBackendType, type] = {
        StorageBackendType.LOCAL: LocalStorage,
        StorageBackendType.SQLITE: SQLiteStorage,
        StorageBackendType.GCS: GCSStorage,
        StorageBackendType.S3: S3Storage,
        StorageBackendType.AZURE: AzureStorage,
    }

    def __init__(
        self,
        config: StorageConfig,
        workflow_name: str,
        enable_cache: bool = True,
    ):
        """
        Initialize StorageManager.

        Args:
            config: Storage configuration
            workflow_name: Name of the workflow (for path resolution)
            enable_cache: Whether to enable local caching for cloud backends
        """
        self.config = config
        self.workflow_name = workflow_name
        self._backend: Optional[IStorageBackend] = None
        self._cache: Optional[StorageCache] = None

        # Initialize backend
        self._initialize_backend()

        # Initialize cache if enabled and backend is cloud-based
        if enable_cache and self._is_cloud_backend():
            cache_config = config.config.get("cache", {})
            self._cache = StorageCache(
                path=cache_config.get("path", "./.storage_cache"),
                max_size=cache_config.get("max_size", "1GB"),
                ttl=cache_config.get("ttl", "1h"),
            )

    def _initialize_backend(self) -> None:
        """Initialize the storage backend."""
        backend_type = self.config.backend

        if backend_type not in self.BACKEND_REGISTRY:
            raise ConfigurationError(
                f"Unknown storage backend: {backend_type.value}",
                context={
                    "backend": backend_type.value,
                    "supported": [b.value for b in self.BACKEND_REGISTRY.keys()],
                }
            )

        backend_class = self.BACKEND_REGISTRY[backend_type]
        backend_config = self.config.config.get(backend_type.value, {})

        try:
            self._backend = backend_class(
                config=self.config,
                backend_config=backend_config,
                workflow_name=self.workflow_name,
            )
            logger.info(
                "Initialized storage backend: %s for workflow: %s",
                backend_type.value,
                self.workflow_name,
            )
        except Exception as e:
            raise StorageError(
                f"Failed to initialize storage backend: {e}",
                context={
                    "backend": backend_type.value,
                    "workflow": self.workflow_name,
                }
            ) from e

    def _is_cloud_backend(self) -> bool:
        """Check if current backend is cloud-based."""
        return self.config.backend in {
            StorageBackendType.GCS,
            StorageBackendType.S3,
            StorageBackendType.AZURE,
        }

    @property
    def backend(self) -> IStorageBackend:
        """Get the underlying storage backend."""
        if self._backend is None:
            raise StorageError("Storage backend not initialized")
        return self._backend

    # =========================================================================
    # Write Operations (delegate to backend)
    # =========================================================================

    def write_output(
        self,
        run_id: str,
        action_name: str,
        data: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StorageLocation:
        """Write action output data."""
        location = self.backend.write_output(run_id, action_name, data, metadata)

        # Invalidate cache if enabled
        if self._cache:
            self._cache.invalidate(location.uri)

        logger.debug(
            "Wrote %d records to %s (run=%s, action=%s)",
            len(data), location.uri, run_id, action_name
        )
        return location

    async def write_output_async(
        self,
        run_id: str,
        action_name: str,
        data: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StorageLocation:
        """Async version of write_output."""
        location = await self.backend.write_output_async(
            run_id, action_name, data, metadata
        )
        if self._cache:
            self._cache.invalidate(location.uri)
        return location

    # =========================================================================
    # Read Operations (with caching)
    # =========================================================================

    def read_output(
        self,
        run_id: str,
        action_name: str,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Read action output data with optional caching."""
        uri = self.backend.get_uri(run_id, action_name)

        # Check cache first
        if self._cache:
            cached = self._cache.get(uri, fields)
            if cached is not None:
                logger.debug("Cache hit for %s", uri)
                return cached

        # Read from backend
        data = self.backend.read_output(run_id, action_name, fields)

        # Populate cache
        if self._cache:
            self._cache.put(uri, data, fields)

        return data

    async def read_output_async(
        self,
        run_id: str,
        action_name: str,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Async version of read_output with caching."""
        uri = self.backend.get_uri(run_id, action_name)

        if self._cache:
            cached = self._cache.get(uri, fields)
            if cached is not None:
                return cached

        data = await self.backend.read_output_async(run_id, action_name, fields)

        if self._cache:
            self._cache.put(uri, data, fields)

        return data

    # =========================================================================
    # Delegate remaining operations
    # =========================================================================

    def write_source(self, *args, **kwargs) -> StorageLocation:
        return self.backend.write_source(*args, **kwargs)

    def read_source(self, *args, **kwargs) -> List[Dict[str, Any]]:
        return self.backend.read_source(*args, **kwargs)

    def read_by_uri(self, uri: str) -> List[Dict[str, Any]]:
        return self.backend.read_by_uri(uri)

    def list_runs(self, filters: Optional[ListRunsFilter] = None) -> List[Dict]:
        return self.backend.list_runs(filters)

    def get_run_metadata(self, run_id: str) -> Dict[str, Any]:
        return self.backend.get_run_metadata(run_id)

    def list_actions(self, run_id: str) -> List[str]:
        return self.backend.list_actions(run_id)

    def delete_run(self, run_id: str) -> bool:
        result = self.backend.delete_run(run_id)
        if result and self._cache:
            self._cache.invalidate_run(run_id)
        return result

    def cleanup(self, older_than: datetime, dry_run: bool = False) -> int:
        return self.backend.cleanup(older_than, dry_run)

    def get_lineage(self, run_id: str, action_name: str) -> Dict[str, Any]:
        return self.backend.get_lineage(run_id, action_name)

    def exists(self, run_id: str, action_name: Optional[str] = None) -> bool:
        return self.backend.exists(run_id, action_name)

    def get_uri(self, run_id: str, action_name: str) -> str:
        return self.backend.get_uri(run_id, action_name)

    # =========================================================================
    # Factory Methods
    # =========================================================================

    @classmethod
    def from_workflow_config(
        cls,
        workflow_config: Dict[str, Any],
        workflow_name: str,
    ) -> "StorageManager":
        """
        Create StorageManager from workflow configuration.

        Args:
            workflow_config: Full workflow configuration dict
            workflow_name: Name of the workflow

        Returns:
            Configured StorageManager instance
        """
        defaults = workflow_config.get("defaults", {})
        storage_dict = defaults.get("storage", {})

        # Use default local storage if not configured
        if not storage_dict:
            storage_dict = {
                "backend": "local",
                "config": {"local": {"base_path": "./agent_io"}},
            }

        config = StorageConfig.from_dict(storage_dict)
        cache_enabled = storage_dict.get("cache", {}).get("enabled", True)

        return cls(
            config=config,
            workflow_name=workflow_name,
            enable_cache=cache_enabled,
        )

    @classmethod
    def from_environment(
        cls,
        workflow_name: str,
        env: Optional[str] = None,
    ) -> "StorageManager":
        """
        Create StorageManager based on environment configuration.

        Args:
            workflow_name: Name of the workflow
            env: Environment name (default from AGENT_ACTIONS_ENV)

        Returns:
            Configured StorageManager instance
        """
        import os
        from pathlib import Path
        import yaml

        env = env or os.environ.get("AGENT_ACTIONS_ENV", "local")
        config_path = Path(f"config/storage.{env}.yml")

        if config_path.exists():
            with open(config_path) as f:
                storage_dict = yaml.safe_load(f).get("storage", {})
        else:
            # Default to local storage
            storage_dict = {
                "backend": "local",
                "config": {"local": {"base_path": "./agent_io"}},
            }

        config = StorageConfig.from_dict(storage_dict)
        return cls(config=config, workflow_name=workflow_name)
```

---

## Backend Implementations

### LocalStorage (Default)

```python
# agent_actions/storage/backends/local.py

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import logging

from agent_actions.storage.interfaces import IStorageBackend
from agent_actions.storage.types import (
    StorageConfig,
    StorageLocation,
    StorageBackendType,
    ListRunsFilter,
)
from agent_actions.errors import StorageReadError, StorageWriteError, DataNotFoundError
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    FileWriteStartedEvent,
    FileWriteCompleteEvent,
)

logger = logging.getLogger(__name__)


class LocalStorage(IStorageBackend):
    """
    Local filesystem storage backend.

    Maintains compatibility with existing agent_io/ directory structure.
    This is the default backend and provides the baseline behavior.
    """

    def __init__(
        self,
        config: StorageConfig,
        backend_config: Dict[str, Any],
        workflow_name: str,
    ):
        """
        Initialize LocalStorage.

        Args:
            config: Full storage configuration
            backend_config: Local-specific config (base_path, etc.)
            workflow_name: Name of the workflow
        """
        self.config = config
        self.workflow_name = workflow_name
        self.base_path = Path(backend_config.get("base_path", "./agent_io"))
        self.options = config.options

        # Ensure base path exists
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_output_path(self, run_id: str, action_name: str) -> Path:
        """Get path for action output."""
        return self.base_path / "target" / action_name / f"{run_id}.json"

    def _get_source_path(self, run_id: str, node_name: str) -> Path:
        """Get path for source data."""
        return self.base_path / "source" / node_name / f"{run_id}.json"

    def _get_metadata_path(self, run_id: str) -> Path:
        """Get path for run metadata."""
        return self.base_path / ".metadata" / f"{run_id}.json"

    # =========================================================================
    # Write Operations
    # =========================================================================

    def write_output(
        self,
        run_id: str,
        action_name: str,
        data: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StorageLocation:
        """Write action output data."""
        path = self._get_output_path(run_id, action_name)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            fire_event(FileWriteStartedEvent(
                file_path=str(path),
                file_type=".json",
            ))

            # Build output with optional lineage
            output = data
            if self.options.lineage_tracking and metadata:
                output = self._add_lineage_to_data(data, metadata, run_id, action_name)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, default=str)

            bytes_written = path.stat().st_size

            fire_event(FileWriteCompleteEvent(
                file_path=str(path),
                file_type=".json",
                bytes_written=bytes_written,
            ))

            # Write metadata
            if metadata:
                self._write_run_metadata(run_id, action_name, metadata)

            uri = f"file://{path.absolute()}"
            return StorageLocation(
                uri=uri,
                backend=StorageBackendType.LOCAL,
                metadata=None,
            )

        except IOError as e:
            raise StorageWriteError(
                f"Failed to write output: {e}",
                context={"path": str(path), "action": action_name, "run_id": run_id}
            ) from e

    def write_source(
        self,
        run_id: str,
        node_name: str,
        data: List[Dict[str, Any]],
        enable_dedup: bool = True,
    ) -> StorageLocation:
        """Write source data with optional deduplication."""
        path = self._get_source_path(run_id, node_name)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Use existing UnifiedSourceDataSaver logic for dedup
            if enable_dedup:
                from agent_actions.output.saver import UnifiedSourceDataSaver
                saver = UnifiedSourceDataSaver(
                    base_directory=str(self.base_path.parent),
                    enable_deduplication=True,
                    enable_locking=True,
                )
                saver.save_source_items(data, f"{node_name}/{run_id}")
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)

            uri = f"file://{path.absolute()}"
            return StorageLocation(uri=uri, backend=StorageBackendType.LOCAL)

        except IOError as e:
            raise StorageWriteError(
                f"Failed to write source: {e}",
                context={"path": str(path), "node": node_name, "run_id": run_id}
            ) from e

    # =========================================================================
    # Read Operations
    # =========================================================================

    def read_output(
        self,
        run_id: str,
        action_name: str,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Read action output data."""
        path = self._get_output_path(run_id, action_name)

        if not path.exists():
            raise DataNotFoundError(
                f"Output not found for action '{action_name}' in run '{run_id}'",
                context={"path": str(path), "action": action_name, "run_id": run_id}
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Apply field filtering (progressive data exposure)
            if fields:
                data = self._filter_fields(data, fields)

            return data

        except json.JSONDecodeError as e:
            raise StorageReadError(
                f"Invalid JSON in output file: {e}",
                context={"path": str(path), "action": action_name}
            ) from e
        except IOError as e:
            raise StorageReadError(
                f"Failed to read output: {e}",
                context={"path": str(path), "action": action_name}
            ) from e

    def read_source(
        self,
        run_id: str,
        node_name: str,
    ) -> List[Dict[str, Any]]:
        """Read source data."""
        path = self._get_source_path(run_id, node_name)

        if not path.exists():
            raise DataNotFoundError(
                f"Source not found for node '{node_name}' in run '{run_id}'",
                context={"path": str(path), "node": node_name, "run_id": run_id}
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise StorageReadError(
                f"Failed to read source: {e}",
                context={"path": str(path), "node": node_name}
            ) from e

    def read_by_uri(self, uri: str) -> List[Dict[str, Any]]:
        """Read data by URI."""
        if not uri.startswith("file://"):
            raise StorageReadError(
                f"LocalStorage can only read file:// URIs, got: {uri}",
                context={"uri": uri}
            )

        path = Path(uri.replace("file://", ""))

        if not path.exists():
            raise DataNotFoundError(
                f"File not found: {path}",
                context={"uri": uri, "path": str(path)}
            )

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # =========================================================================
    # Query Operations
    # =========================================================================

    def list_runs(
        self,
        filters: Optional[ListRunsFilter] = None,
    ) -> List[Dict[str, Any]]:
        """List workflow runs with optional filters."""
        runs = []
        metadata_dir = self.base_path / ".metadata"

        if not metadata_dir.exists():
            return runs

        for meta_file in metadata_dir.glob("*.json"):
            run_id = meta_file.stem

            try:
                with open(meta_file, "r") as f:
                    metadata = json.load(f)

                # Apply filters
                if filters:
                    if filters.workflow_name and metadata.get("workflow_name") != filters.workflow_name:
                        continue
                    if filters.since:
                        run_time = datetime.fromisoformat(metadata.get("timestamp", ""))
                        if run_time < filters.since:
                            continue
                    if filters.status and metadata.get("status") != filters.status:
                        continue

                runs.append({"run_id": run_id, **metadata})

            except (json.JSONDecodeError, IOError):
                logger.warning("Failed to read metadata for run %s", run_id)
                continue

        # Sort by timestamp descending
        runs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Apply limit/offset
        if filters:
            runs = runs[filters.offset:filters.offset + filters.limit]

        return runs

    def get_run_metadata(self, run_id: str) -> Dict[str, Any]:
        """Get metadata for a specific run."""
        path = self._get_metadata_path(run_id)

        if not path.exists():
            raise DataNotFoundError(
                f"Run metadata not found: {run_id}",
                context={"run_id": run_id}
            )

        with open(path, "r") as f:
            return json.load(f)

    def list_actions(self, run_id: str) -> List[str]:
        """List all actions in a run."""
        target_dir = self.base_path / "target"
        actions = []

        if not target_dir.exists():
            return actions

        for action_dir in target_dir.iterdir():
            if action_dir.is_dir():
                # Check if this run has output in this action
                run_file = action_dir / f"{run_id}.json"
                if run_file.exists():
                    actions.append(action_dir.name)

        return actions

    # =========================================================================
    # Delete Operations
    # =========================================================================

    def delete_run(self, run_id: str) -> bool:
        """Delete all data for a run."""
        deleted = False

        # Delete from target/
        target_dir = self.base_path / "target"
        if target_dir.exists():
            for action_dir in target_dir.iterdir():
                run_file = action_dir / f"{run_id}.json"
                if run_file.exists():
                    run_file.unlink()
                    deleted = True

        # Delete from source/
        source_dir = self.base_path / "source"
        if source_dir.exists():
            for node_dir in source_dir.iterdir():
                run_file = node_dir / f"{run_id}.json"
                if run_file.exists():
                    run_file.unlink()
                    deleted = True

        # Delete metadata
        meta_file = self._get_metadata_path(run_id)
        if meta_file.exists():
            meta_file.unlink()
            deleted = True

        return deleted

    def cleanup(
        self,
        older_than: datetime,
        dry_run: bool = False,
    ) -> int:
        """Delete runs older than specified date."""
        deleted_count = 0

        for run in self.list_runs():
            run_time = datetime.fromisoformat(run.get("timestamp", ""))
            if run_time < older_than:
                if dry_run:
                    logger.info("Would delete run: %s", run["run_id"])
                else:
                    if self.delete_run(run["run_id"]):
                        logger.info("Deleted run: %s", run["run_id"])
                deleted_count += 1

        return deleted_count

    # =========================================================================
    # Lineage Operations
    # =========================================================================

    def get_lineage(
        self,
        run_id: str,
        action_name: str,
    ) -> Dict[str, Any]:
        """Get lineage information for an action's output."""
        metadata = self.get_run_metadata(run_id)
        action_meta = metadata.get("actions", {}).get(action_name, {})
        return action_meta.get("lineage", {})

    def get_downstream_lineage(
        self,
        run_id: str,
        action_name: str,
        depth: int = -1,
    ) -> List[Dict[str, Any]]:
        """Get all downstream actions that consumed this action's output."""
        # For local storage, we need to scan metadata
        downstream = []
        uri = self.get_uri(run_id, action_name)

        # Scan all action metadata for references to this URI
        metadata = self.get_run_metadata(run_id)
        for other_action, action_meta in metadata.get("actions", {}).items():
            inputs = action_meta.get("lineage", {}).get("inputs", [])
            if uri in inputs:
                downstream.append({
                    "action": other_action,
                    "run_id": run_id,
                    "lineage": action_meta.get("lineage", {}),
                })

        return downstream

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def exists(self, run_id: str, action_name: Optional[str] = None) -> bool:
        """Check if data exists."""
        if action_name:
            return self._get_output_path(run_id, action_name).exists()
        return self._get_metadata_path(run_id).exists()

    def get_uri(self, run_id: str, action_name: str) -> str:
        """Get URI for action output without reading data."""
        path = self._get_output_path(run_id, action_name)
        return f"file://{path.absolute()}"

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _filter_fields(
        self,
        data: List[Dict[str, Any]],
        fields: List[str],
    ) -> List[Dict[str, Any]]:
        """Filter data to only include specified fields."""
        if not fields:
            return data

        filtered = []
        for record in data:
            filtered_record = {}
            for field in fields:
                if "." in field:
                    # Handle nested fields (e.g., "content.name")
                    parts = field.split(".")
                    value = record
                    for part in parts:
                        if isinstance(value, dict):
                            value = value.get(part)
                        else:
                            value = None
                            break
                    if value is not None:
                        # Set nested value
                        self._set_nested(filtered_record, parts, value)
                elif field in record:
                    filtered_record[field] = record[field]
            filtered.append(filtered_record)

        return filtered

    def _set_nested(self, d: Dict, keys: List[str], value: Any) -> None:
        """Set a nested dictionary value."""
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value

    def _add_lineage_to_data(
        self,
        data: List[Dict[str, Any]],
        metadata: Dict[str, Any],
        run_id: str,
        action_name: str,
    ) -> List[Dict[str, Any]]:
        """Add lineage tracking to data records."""
        from agent_actions import __version__

        lineage_info = {
            "run_id": run_id,
            "action": action_name,
            "workflow": self.workflow_name,
            "timestamp": datetime.utcnow().isoformat(),
            "inputs": metadata.get("inputs", []),
            "schema_version": metadata.get("schema_version", "1.0.0"),
            "agent_actions_version": __version__,
        }

        for record in data:
            if isinstance(record, dict):
                record["_lineage"] = lineage_info

        return data

    def _write_run_metadata(
        self,
        run_id: str,
        action_name: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Write or update run metadata."""
        path = self._get_metadata_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        existing = {}
        if path.exists():
            with open(path, "r") as f:
                existing = json.load(f)

        # Update action metadata
        existing.setdefault("actions", {})[action_name] = {
            "timestamp": datetime.utcnow().isoformat(),
            "record_count": metadata.get("record_count", 0),
            "lineage": metadata.get("lineage", {}),
        }
        existing["workflow_name"] = self.workflow_name
        existing["timestamp"] = datetime.utcnow().isoformat()

        with open(path, "w") as f:
            json.dump(existing, f, indent=2, default=str)
```

### GCSStorage (Example Cloud Backend)

```python
# agent_actions/storage/backends/gcs.py

"""
Google Cloud Storage backend.

Requires: google-cloud-storage package
Install: pip install google-cloud-storage
"""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime
import logging

from agent_actions.storage.interfaces import IStorageBackend
from agent_actions.storage.types import (
    StorageConfig,
    StorageLocation,
    StorageBackendType,
    ListRunsFilter,
)
from agent_actions.errors import StorageReadError, StorageWriteError, DataNotFoundError

logger = logging.getLogger(__name__)


class GCSStorage(IStorageBackend):
    """
    Google Cloud Storage backend.

    Stores workflow data in GCS buckets with the following structure:

    gs://{bucket}/{prefix}/
    ├── runs/
    │   └── {run_id}/
    │       ├── metadata.json
    │       ├── target/
    │       │   └── {action_name}.json
    │       └── source/
    │           └── {node_name}.json
    └── index/
        └── runs.json  # Index for fast listing
    """

    def __init__(
        self,
        config: StorageConfig,
        backend_config: Dict[str, Any],
        workflow_name: str,
    ):
        """Initialize GCSStorage."""
        try:
            from google.cloud import storage
        except ImportError:
            raise ImportError(
                "google-cloud-storage is required for GCS backend. "
                "Install with: pip install google-cloud-storage"
            )

        self.config = config
        self.workflow_name = workflow_name
        self.bucket_name = backend_config["bucket"]
        self.prefix = backend_config.get("prefix", "").format(
            workflow_name=workflow_name
        ).strip("/")

        # Initialize client
        project = backend_config.get("project")
        credentials_path = backend_config.get("credentials")

        if credentials_path:
            import os
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        self.client = storage.Client(project=project)
        self.bucket = self.client.bucket(self.bucket_name)
        self.options = config.options

    def _get_blob_path(self, run_id: str, category: str, name: str) -> str:
        """Get blob path for data."""
        if self.prefix:
            return f"{self.prefix}/runs/{run_id}/{category}/{name}.json"
        return f"runs/{run_id}/{category}/{name}.json"

    def _get_metadata_path(self, run_id: str) -> str:
        """Get blob path for run metadata."""
        if self.prefix:
            return f"{self.prefix}/runs/{run_id}/metadata.json"
        return f"runs/{run_id}/metadata.json"

    # =========================================================================
    # Write Operations
    # =========================================================================

    def write_output(
        self,
        run_id: str,
        action_name: str,
        data: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StorageLocation:
        """Write action output to GCS."""
        blob_path = self._get_blob_path(run_id, "target", action_name)
        blob = self.bucket.blob(blob_path)

        try:
            # Add lineage if enabled
            if self.options.lineage_tracking and metadata:
                data = self._add_lineage_to_data(data, metadata, run_id, action_name)

            # Serialize with compression
            content = json.dumps(data, indent=2, default=str)
            content_type = "application/json"

            if self.options.compression.value != "none":
                content, content_type = self._compress(content)

            blob.upload_from_string(content, content_type=content_type)

            # Set metadata
            if metadata:
                blob.metadata = {
                    "run_id": run_id,
                    "action": action_name,
                    "workflow": self.workflow_name,
                    "record_count": str(len(data)),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                blob.patch()

            # Update run metadata
            self._update_run_metadata(run_id, action_name, metadata)

            uri = f"gs://{self.bucket_name}/{blob_path}"
            logger.info("Wrote %d records to %s", len(data), uri)

            return StorageLocation(uri=uri, backend=StorageBackendType.GCS)

        except Exception as e:
            raise StorageWriteError(
                f"Failed to write to GCS: {e}",
                context={
                    "bucket": self.bucket_name,
                    "path": blob_path,
                    "action": action_name,
                }
            ) from e

    def write_source(
        self,
        run_id: str,
        node_name: str,
        data: List[Dict[str, Any]],
        enable_dedup: bool = True,
    ) -> StorageLocation:
        """Write source data to GCS."""
        blob_path = self._get_blob_path(run_id, "source", node_name)
        blob = self.bucket.blob(blob_path)

        try:
            # Deduplication for GCS requires read-modify-write
            if enable_dedup and blob.exists():
                existing = json.loads(blob.download_as_string())
                existing_guids = {r.get("source_guid") for r in existing}
                new_records = [r for r in data if r.get("source_guid") not in existing_guids]
                data = existing + new_records

            content = json.dumps(data, indent=2, default=str)
            blob.upload_from_string(content, content_type="application/json")

            uri = f"gs://{self.bucket_name}/{blob_path}"
            return StorageLocation(uri=uri, backend=StorageBackendType.GCS)

        except Exception as e:
            raise StorageWriteError(
                f"Failed to write source to GCS: {e}",
                context={"bucket": self.bucket_name, "path": blob_path}
            ) from e

    # =========================================================================
    # Read Operations
    # =========================================================================

    def read_output(
        self,
        run_id: str,
        action_name: str,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Read action output from GCS."""
        blob_path = self._get_blob_path(run_id, "target", action_name)
        blob = self.bucket.blob(blob_path)

        if not blob.exists():
            raise DataNotFoundError(
                f"Output not found: gs://{self.bucket_name}/{blob_path}",
                context={"run_id": run_id, "action": action_name}
            )

        try:
            content = blob.download_as_string()

            # Decompress if needed
            if self.options.compression.value != "none":
                content = self._decompress(content)

            data = json.loads(content)

            # Apply field filtering
            if fields:
                data = self._filter_fields(data, fields)

            return data

        except Exception as e:
            raise StorageReadError(
                f"Failed to read from GCS: {e}",
                context={"bucket": self.bucket_name, "path": blob_path}
            ) from e

    def read_source(
        self,
        run_id: str,
        node_name: str,
    ) -> List[Dict[str, Any]]:
        """Read source data from GCS."""
        blob_path = self._get_blob_path(run_id, "source", node_name)
        blob = self.bucket.blob(blob_path)

        if not blob.exists():
            raise DataNotFoundError(
                f"Source not found: gs://{self.bucket_name}/{blob_path}",
                context={"run_id": run_id, "node": node_name}
            )

        return json.loads(blob.download_as_string())

    def read_by_uri(self, uri: str) -> List[Dict[str, Any]]:
        """Read data by GCS URI."""
        if not uri.startswith("gs://"):
            raise StorageReadError(
                f"GCSStorage can only read gs:// URIs, got: {uri}",
                context={"uri": uri}
            )

        # Parse gs://bucket/path
        parts = uri[5:].split("/", 1)
        bucket_name = parts[0]
        blob_path = parts[1] if len(parts) > 1 else ""

        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        if not blob.exists():
            raise DataNotFoundError(f"Blob not found: {uri}")

        return json.loads(blob.download_as_string())

    # =========================================================================
    # Query Operations
    # =========================================================================

    def list_runs(
        self,
        filters: Optional[ListRunsFilter] = None,
    ) -> List[Dict[str, Any]]:
        """List runs from GCS."""
        runs = []
        prefix = f"{self.prefix}/runs/" if self.prefix else "runs/"

        # List all run directories
        blobs = self.client.list_blobs(
            self.bucket_name,
            prefix=prefix,
            delimiter="/",
        )

        # Extract run IDs from prefixes
        for page in blobs.pages:
            for prefix_path in page.prefixes:
                run_id = prefix_path.rstrip("/").split("/")[-1]

                try:
                    metadata = self.get_run_metadata(run_id)

                    # Apply filters
                    if filters:
                        if filters.workflow_name and metadata.get("workflow_name") != filters.workflow_name:
                            continue
                        if filters.since:
                            run_time = datetime.fromisoformat(metadata.get("timestamp", ""))
                            if run_time < filters.since:
                                continue

                    runs.append({"run_id": run_id, **metadata})

                except DataNotFoundError:
                    continue

        # Sort and paginate
        runs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        if filters:
            runs = runs[filters.offset:filters.offset + filters.limit]

        return runs

    def get_run_metadata(self, run_id: str) -> Dict[str, Any]:
        """Get run metadata from GCS."""
        blob_path = self._get_metadata_path(run_id)
        blob = self.bucket.blob(blob_path)

        if not blob.exists():
            raise DataNotFoundError(f"Run metadata not found: {run_id}")

        return json.loads(blob.download_as_string())

    def list_actions(self, run_id: str) -> List[str]:
        """List all actions in a run."""
        prefix = self._get_blob_path(run_id, "target", "").rstrip("/") + "/"

        actions = []
        blobs = self.client.list_blobs(self.bucket_name, prefix=prefix)

        for blob in blobs:
            action_name = blob.name.split("/")[-1].replace(".json", "")
            if action_name:
                actions.append(action_name)

        return actions

    # =========================================================================
    # Delete Operations
    # =========================================================================

    def delete_run(self, run_id: str) -> bool:
        """Delete all data for a run from GCS."""
        prefix = f"{self.prefix}/runs/{run_id}/" if self.prefix else f"runs/{run_id}/"

        blobs = list(self.client.list_blobs(self.bucket_name, prefix=prefix))

        if not blobs:
            return False

        for blob in blobs:
            blob.delete()

        logger.info("Deleted %d blobs for run %s", len(blobs), run_id)
        return True

    def cleanup(
        self,
        older_than: datetime,
        dry_run: bool = False,
    ) -> int:
        """Delete runs older than specified date."""
        deleted_count = 0

        for run in self.list_runs():
            run_time = datetime.fromisoformat(run.get("timestamp", ""))
            if run_time < older_than:
                if dry_run:
                    logger.info("Would delete run: %s", run["run_id"])
                else:
                    self.delete_run(run["run_id"])
                deleted_count += 1

        return deleted_count

    # =========================================================================
    # Lineage Operations
    # =========================================================================

    def get_lineage(
        self,
        run_id: str,
        action_name: str,
    ) -> Dict[str, Any]:
        """Get lineage information."""
        metadata = self.get_run_metadata(run_id)
        return metadata.get("actions", {}).get(action_name, {}).get("lineage", {})

    def get_downstream_lineage(
        self,
        run_id: str,
        action_name: str,
        depth: int = -1,
    ) -> List[Dict[str, Any]]:
        """Get downstream lineage."""
        downstream = []
        uri = self.get_uri(run_id, action_name)

        metadata = self.get_run_metadata(run_id)
        for other_action, action_meta in metadata.get("actions", {}).items():
            inputs = action_meta.get("lineage", {}).get("inputs", [])
            if uri in inputs:
                downstream.append({
                    "action": other_action,
                    "run_id": run_id,
                    "lineage": action_meta.get("lineage", {}),
                })

        return downstream

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def exists(self, run_id: str, action_name: Optional[str] = None) -> bool:
        """Check if data exists in GCS."""
        if action_name:
            blob_path = self._get_blob_path(run_id, "target", action_name)
        else:
            blob_path = self._get_metadata_path(run_id)

        return self.bucket.blob(blob_path).exists()

    def get_uri(self, run_id: str, action_name: str) -> str:
        """Get GCS URI for action output."""
        blob_path = self._get_blob_path(run_id, "target", action_name)
        return f"gs://{self.bucket_name}/{blob_path}"

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _update_run_metadata(
        self,
        run_id: str,
        action_name: str,
        metadata: Optional[Dict[str, Any]],
    ) -> None:
        """Update run metadata in GCS."""
        blob_path = self._get_metadata_path(run_id)
        blob = self.bucket.blob(blob_path)

        existing = {}
        if blob.exists():
            existing = json.loads(blob.download_as_string())

        existing.setdefault("actions", {})[action_name] = {
            "timestamp": datetime.utcnow().isoformat(),
            "lineage": metadata.get("lineage", {}) if metadata else {},
        }
        existing["workflow_name"] = self.workflow_name
        existing["timestamp"] = datetime.utcnow().isoformat()

        blob.upload_from_string(
            json.dumps(existing, indent=2, default=str),
            content_type="application/json",
        )

    def _compress(self, content: str) -> tuple:
        """Compress content based on configured compression."""
        import gzip

        if self.options.compression.value == "gzip":
            return gzip.compress(content.encode()), "application/gzip"
        # Add zstd, snappy as needed
        return content, "application/json"

    def _decompress(self, content: bytes) -> str:
        """Decompress content."""
        import gzip

        if self.options.compression.value == "gzip":
            return gzip.decompress(content).decode()
        return content.decode()

    def _filter_fields(
        self,
        data: List[Dict[str, Any]],
        fields: List[str],
    ) -> List[Dict[str, Any]]:
        """Filter to specified fields only."""
        if not fields:
            return data

        filtered = []
        for record in data:
            filtered_record = {k: v for k, v in record.items() if k in fields}
            filtered.append(filtered_record)
        return filtered

    def _add_lineage_to_data(
        self,
        data: List[Dict[str, Any]],
        metadata: Dict[str, Any],
        run_id: str,
        action_name: str,
    ) -> List[Dict[str, Any]]:
        """Add lineage tracking to data."""
        from agent_actions import __version__

        lineage_info = {
            "run_id": run_id,
            "action": action_name,
            "workflow": self.workflow_name,
            "timestamp": datetime.utcnow().isoformat(),
            "inputs": metadata.get("inputs", []),
            "agent_actions_version": __version__,
        }

        for record in data:
            if isinstance(record, dict):
                record["_lineage"] = lineage_info

        return data
```

---

## URI-Based Data References

### URI Resolver

```python
# agent_actions/storage/uri.py

from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qs
import logging

from agent_actions.storage.types import StorageBackendType
from agent_actions.storage.interfaces import IStorageBackend
from agent_actions.errors import StorageError

logger = logging.getLogger(__name__)


class URIResolver:
    """
    Resolves storage URIs to appropriate backends and reads data.

    Supported URI schemes:
    - file://     → LocalStorage
    - gs://       → GCSStorage
    - s3://       → S3Storage
    - azure://    → AzureStorage
    - sqlite://   → SQLiteStorage
    """

    SCHEME_TO_BACKEND: Dict[str, StorageBackendType] = {
        "file": StorageBackendType.LOCAL,
        "gs": StorageBackendType.GCS,
        "s3": StorageBackendType.S3,
        "azure": StorageBackendType.AZURE,
        "sqlite": StorageBackendType.SQLITE,
    }

    def __init__(self, backends: Dict[StorageBackendType, IStorageBackend]):
        """
        Initialize URIResolver with available backends.

        Args:
            backends: Map of backend type to initialized backend instance
        """
        self.backends = backends

    def resolve(self, uri: str) -> List[Dict[str, Any]]:
        """
        Resolve URI and read data.

        Args:
            uri: Storage URI (e.g., "gs://bucket/path/data.json")

        Returns:
            List of data records

        Raises:
            StorageError: If scheme not supported or backend not available
        """
        parsed = urlparse(uri)
        scheme = parsed.scheme or "file"

        if scheme not in self.SCHEME_TO_BACKEND:
            raise StorageError(
                f"Unsupported URI scheme: {scheme}",
                context={"uri": uri, "supported": list(self.SCHEME_TO_BACKEND.keys())}
            )

        backend_type = self.SCHEME_TO_BACKEND[scheme]

        if backend_type not in self.backends:
            raise StorageError(
                f"Backend not configured for scheme: {scheme}",
                context={"uri": uri, "backend": backend_type.value}
            )

        backend = self.backends[backend_type]
        return backend.read_by_uri(uri)

    def get_backend_for_uri(self, uri: str) -> IStorageBackend:
        """Get the appropriate backend for a URI."""
        parsed = urlparse(uri)
        scheme = parsed.scheme or "file"

        if scheme not in self.SCHEME_TO_BACKEND:
            raise StorageError(f"Unsupported URI scheme: {scheme}")

        backend_type = self.SCHEME_TO_BACKEND[scheme]

        if backend_type not in self.backends:
            raise StorageError(f"Backend not configured: {backend_type.value}")

        return self.backends[backend_type]


def parse_storage_uri(uri: str) -> Dict[str, Any]:
    """
    Parse a storage URI into components.

    Args:
        uri: Storage URI

    Returns:
        Dictionary with scheme, bucket/path, and query parameters
    """
    parsed = urlparse(uri)

    return {
        "scheme": parsed.scheme or "file",
        "host": parsed.netloc,
        "path": parsed.path,
        "query": parse_qs(parsed.query),
    }
```

---

## Caching Layer

```python
# agent_actions/storage/cache.py

from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime, timedelta
import json
import hashlib
import logging

logger = logging.getLogger(__name__)


class StorageCache:
    """
    Local caching layer for cloud storage backends.

    Reduces cloud API calls during development and debugging by
    caching recently accessed data locally.
    """

    def __init__(
        self,
        path: str = "./.storage_cache",
        max_size: str = "1GB",
        ttl: str = "1h",
    ):
        """
        Initialize storage cache.

        Args:
            path: Local cache directory
            max_size: Maximum cache size (e.g., "1GB", "500MB")
            ttl: Cache entry TTL (e.g., "1h", "30m", "1d")
        """
        self.cache_dir = Path(path)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_bytes = self._parse_size(max_size)
        self.ttl_seconds = self._parse_duration(ttl)
        self._index: Dict[str, Dict] = {}
        self._load_index()

    def get(
        self,
        uri: str,
        fields: Optional[List[str]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get data from cache.

        Args:
            uri: Storage URI
            fields: Optional field filter (cache stores full data)

        Returns:
            Cached data or None if not found/expired
        """
        cache_key = self._cache_key(uri)

        if cache_key not in self._index:
            return None

        entry = self._index[cache_key]

        # Check TTL
        cached_at = datetime.fromisoformat(entry["cached_at"])
        if datetime.utcnow() - cached_at > timedelta(seconds=self.ttl_seconds):
            self.invalidate(uri)
            return None

        # Read from cache file
        cache_file = self.cache_dir / f"{cache_key}.json"
        if not cache_file.exists():
            del self._index[cache_key]
            self._save_index()
            return None

        try:
            with open(cache_file, "r") as f:
                data = json.load(f)

            # Apply field filtering if requested
            if fields:
                data = self._filter_fields(data, fields)

            logger.debug("Cache hit: %s", uri)
            return data

        except (json.JSONDecodeError, IOError):
            self.invalidate(uri)
            return None

    def put(
        self,
        uri: str,
        data: List[Dict[str, Any]],
        fields: Optional[List[str]] = None,
    ) -> None:
        """
        Store data in cache.

        Args:
            uri: Storage URI
            data: Data to cache
            fields: Optional - if provided, we cache full data but note the filter
        """
        # Enforce cache size limit
        self._enforce_size_limit()

        cache_key = self._cache_key(uri)
        cache_file = self.cache_dir / f"{cache_key}.json"

        try:
            with open(cache_file, "w") as f:
                json.dump(data, f)

            self._index[cache_key] = {
                "uri": uri,
                "cached_at": datetime.utcnow().isoformat(),
                "size": cache_file.stat().st_size,
            }
            self._save_index()

            logger.debug("Cached: %s (%d bytes)", uri, cache_file.stat().st_size)

        except IOError as e:
            logger.warning("Failed to cache %s: %s", uri, e)

    def invalidate(self, uri: str) -> None:
        """Invalidate a cache entry."""
        cache_key = self._cache_key(uri)

        if cache_key in self._index:
            cache_file = self.cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                cache_file.unlink()
            del self._index[cache_key]
            self._save_index()
            logger.debug("Invalidated cache: %s", uri)

    def invalidate_run(self, run_id: str) -> None:
        """Invalidate all cache entries for a run."""
        keys_to_remove = [
            key for key, entry in self._index.items()
            if run_id in entry.get("uri", "")
        ]
        for key in keys_to_remove:
            cache_file = self.cache_dir / f"{key}.json"
            if cache_file.exists():
                cache_file.unlink()
            del self._index[key]

        if keys_to_remove:
            self._save_index()
            logger.debug("Invalidated %d cache entries for run %s", len(keys_to_remove), run_id)

    def clear(self) -> None:
        """Clear entire cache."""
        for cache_file in self.cache_dir.glob("*.json"):
            if cache_file.name != "_index.json":
                cache_file.unlink()
        self._index = {}
        self._save_index()
        logger.info("Cache cleared")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _cache_key(self, uri: str) -> str:
        """Generate cache key from URI."""
        return hashlib.sha256(uri.encode()).hexdigest()[:16]

    def _load_index(self) -> None:
        """Load cache index from disk."""
        index_file = self.cache_dir / "_index.json"
        if index_file.exists():
            try:
                with open(index_file, "r") as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._index = {}

    def _save_index(self) -> None:
        """Save cache index to disk."""
        index_file = self.cache_dir / "_index.json"
        with open(index_file, "w") as f:
            json.dump(self._index, f, indent=2)

    def _enforce_size_limit(self) -> None:
        """Evict old entries if cache exceeds size limit."""
        total_size = sum(entry.get("size", 0) for entry in self._index.values())

        if total_size <= self.max_size_bytes:
            return

        # Sort by cached_at (oldest first)
        sorted_entries = sorted(
            self._index.items(),
            key=lambda x: x[1].get("cached_at", ""),
        )

        # Evict until under limit
        for cache_key, entry in sorted_entries:
            if total_size <= self.max_size_bytes * 0.8:  # Keep 20% headroom
                break

            cache_file = self.cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                total_size -= entry.get("size", 0)
                cache_file.unlink()
                del self._index[cache_key]

        self._save_index()

    def _parse_size(self, size_str: str) -> int:
        """Parse size string to bytes."""
        size_str = size_str.upper()
        multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}

        for suffix, mult in multipliers.items():
            if size_str.endswith(suffix):
                return int(float(size_str[:-len(suffix)]) * mult)

        return int(size_str)

    def _parse_duration(self, duration_str: str) -> int:
        """Parse duration string to seconds."""
        duration_str = duration_str.lower()
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}

        for suffix, mult in multipliers.items():
            if duration_str.endswith(suffix):
                return int(float(duration_str[:-len(suffix)]) * mult)

        return int(duration_str)

    def _filter_fields(
        self,
        data: List[Dict[str, Any]],
        fields: List[str],
    ) -> List[Dict[str, Any]]:
        """Filter cached data to requested fields."""
        return [
            {k: v for k, v in record.items() if k in fields}
            for record in data
        ]
```

---

## CLI Commands

### Storage Command Group

```python
# agent_actions/cli/commands/storage.py

import click
from datetime import datetime, timedelta
from pathlib import Path
import json

from agent_actions.storage.manager import StorageManager
from agent_actions.storage.types import ListRunsFilter
from agent_actions.cli.cli_decorators import handle_errors


@click.group(name="storage")
def storage():
    """Storage management commands."""
    pass


@storage.command(name="list")
@click.option("--workflow", "-w", help="Filter by workflow name")
@click.option("--since", "-s", help="Filter runs since (e.g., '7d', '24h', '2024-01-01')")
@click.option("--status", help="Filter by status")
@click.option("--limit", "-n", default=20, help="Number of results")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@handle_errors
def list_runs(workflow, since, status, limit, fmt):
    """List workflow runs."""
    manager = StorageManager.from_environment(workflow_name=workflow or "*")

    # Parse since
    since_dt = None
    if since:
        since_dt = _parse_since(since)

    filters = ListRunsFilter(
        workflow_name=workflow,
        since=since_dt,
        status=status,
        limit=limit,
    )

    runs = manager.list_runs(filters)

    if fmt == "json":
        click.echo(json.dumps(runs, indent=2, default=str))
    else:
        _print_runs_table(runs)


@storage.command(name="inspect")
@click.argument("run_id")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@handle_errors
def inspect_run(run_id, fmt):
    """Inspect a specific run."""
    manager = StorageManager.from_environment(workflow_name="*")

    metadata = manager.get_run_metadata(run_id)
    actions = manager.list_actions(run_id)

    result = {
        "run_id": run_id,
        **metadata,
        "actions": actions,
    }

    if fmt == "json":
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        click.echo(f"\n{'='*60}")
        click.echo(f"Run: {run_id}")
        click.echo(f"{'='*60}")
        click.echo(f"Workflow: {metadata.get('workflow_name', 'unknown')}")
        click.echo(f"Timestamp: {metadata.get('timestamp', 'unknown')}")
        click.echo(f"Actions: {len(actions)}")
        click.echo("\nActions:")
        for action in actions:
            click.echo(f"  - {action}")


@storage.command(name="export")
@click.argument("run_id")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output directory")
@click.option("--action", "-a", help="Export specific action only")
@handle_errors
def export_run(run_id, output, action):
    """Export run data to local files."""
    manager = StorageManager.from_environment(workflow_name="*")
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    actions_to_export = [action] if action else manager.list_actions(run_id)

    for action_name in actions_to_export:
        data = manager.read_output(run_id, action_name)
        output_file = output_dir / f"{action_name}.json"

        with open(output_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

        click.echo(f"Exported: {output_file} ({len(data)} records)")

    # Export metadata
    metadata = manager.get_run_metadata(run_id)
    meta_file = output_dir / "_metadata.json"
    with open(meta_file, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    click.echo(f"\nExported run {run_id} to {output_dir}")


@storage.command(name="cleanup")
@click.option("--older-than", required=True, help="Delete runs older than (e.g., '30d', '90d')")
@click.option("--workflow", "-w", help="Filter by workflow")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
@click.confirmation_option(prompt="Are you sure you want to delete old runs?")
@handle_errors
def cleanup(older_than, workflow, dry_run):
    """Delete runs older than specified age."""
    manager = StorageManager.from_environment(workflow_name=workflow or "*")

    cutoff = datetime.utcnow() - _parse_duration(older_than)

    if dry_run:
        click.echo(f"Dry run - would delete runs older than {cutoff}")

    deleted = manager.cleanup(cutoff, dry_run=dry_run)

    if dry_run:
        click.echo(f"Would delete {deleted} runs")
    else:
        click.echo(f"Deleted {deleted} runs")


@storage.command(name="lineage")
@click.argument("run_id")
@click.argument("action_name")
@click.option("--upstream", is_flag=True, help="Show upstream lineage")
@click.option("--downstream", is_flag=True, help="Show downstream lineage")
@handle_errors
def show_lineage(run_id, action_name, upstream, downstream):
    """Show data lineage for an action."""
    manager = StorageManager.from_environment(workflow_name="*")

    lineage = manager.get_lineage(run_id, action_name)

    click.echo(f"\nLineage for {action_name} (run: {run_id})")
    click.echo("=" * 60)

    if upstream or (not upstream and not downstream):
        click.echo("\nInputs:")
        for input_uri in lineage.get("inputs", []):
            click.echo(f"  ← {input_uri}")

    if downstream:
        downstream_actions = manager.backend.get_downstream_lineage(run_id, action_name)
        click.echo("\nDownstream:")
        for ds in downstream_actions:
            click.echo(f"  → {ds['action']}")


@storage.command(name="migrate")
@click.option("--from", "from_env", required=True, help="Source environment")
@click.option("--to", "to_env", required=True, help="Target environment")
@click.option("--workflow", "-w", required=True, help="Workflow to migrate")
@click.option("--run", "run_id", help="Specific run to migrate (default: all)")
@click.option("--dry-run", is_flag=True, help="Show what would be migrated")
@handle_errors
def migrate(from_env, to_env, workflow, run_id, dry_run):
    """Migrate data between storage backends."""
    source = StorageManager.from_environment(workflow_name=workflow, env=from_env)
    target = StorageManager.from_environment(workflow_name=workflow, env=to_env)

    if run_id:
        runs = [{"run_id": run_id}]
    else:
        runs = source.list_runs(ListRunsFilter(workflow_name=workflow))

    click.echo(f"Migrating {len(runs)} runs from {from_env} to {to_env}")

    for run in runs:
        rid = run["run_id"]
        actions = source.list_actions(rid)

        if dry_run:
            click.echo(f"  Would migrate: {rid} ({len(actions)} actions)")
            continue

        for action in actions:
            data = source.read_output(rid, action)
            metadata = source.backend.get_lineage(rid, action)
            target.write_output(rid, action, data, {"lineage": metadata})

        click.echo(f"  Migrated: {rid} ({len(actions)} actions)")

    click.echo("Migration complete")


# =========================================================================
# Helper Functions
# =========================================================================

def _parse_since(since_str: str) -> datetime:
    """Parse 'since' string to datetime."""
    try:
        return datetime.fromisoformat(since_str)
    except ValueError:
        pass

    # Parse relative time (e.g., "7d", "24h")
    duration = _parse_duration(since_str)
    return datetime.utcnow() - duration


def _parse_duration(duration_str: str) -> timedelta:
    """Parse duration string to timedelta."""
    duration_str = duration_str.lower()

    if duration_str.endswith("d"):
        return timedelta(days=int(duration_str[:-1]))
    elif duration_str.endswith("h"):
        return timedelta(hours=int(duration_str[:-1]))
    elif duration_str.endswith("m"):
        return timedelta(minutes=int(duration_str[:-1]))
    else:
        return timedelta(days=int(duration_str))


def _print_runs_table(runs):
    """Print runs in table format."""
    if not runs:
        click.echo("No runs found")
        return

    click.echo(f"\n{'Run ID':<20} {'Workflow':<25} {'Timestamp':<25} {'Actions':<10}")
    click.echo("-" * 80)

    for run in runs:
        run_id = run.get("run_id", "")[:18]
        workflow = run.get("workflow_name", "")[:23]
        timestamp = run.get("timestamp", "")[:23]
        actions = str(len(run.get("actions", {})))

        click.echo(f"{run_id:<20} {workflow:<25} {timestamp:<25} {actions:<10}")
```

---

## Lineage Tracking

### Lineage Data Model

Lineage is tracked at multiple levels:

1. **Record-level**: Each output record contains `_lineage` field
2. **Action-level**: Metadata tracks input URIs for each action
3. **Run-level**: Complete dependency graph for the workflow run

```python
# agent_actions/storage/lineage.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class LineageRecord:
    """Lineage information for a single output."""

    run_id: str
    action: str
    workflow: str
    timestamp: datetime
    inputs: List[str]  # URIs of input data
    source_guids: List[str]  # Source records that contributed
    schema_version: str
    agent_actions_version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "action": self.action,
            "workflow": self.workflow,
            "timestamp": self.timestamp.isoformat(),
            "inputs": self.inputs,
            "source_guids": self.source_guids,
            "schema_version": self.schema_version,
            "agent_actions_version": self.agent_actions_version,
        }


@dataclass
class LineageGraph:
    """Complete lineage graph for a workflow run."""

    run_id: str
    workflow: str
    nodes: Dict[str, LineageRecord] = field(default_factory=dict)
    edges: List[tuple] = field(default_factory=list)  # (from_action, to_action)

    def add_node(self, action: str, lineage: LineageRecord) -> None:
        """Add an action to the graph."""
        self.nodes[action] = lineage

        # Add edges from inputs
        for input_uri in lineage.inputs:
            input_action = self._extract_action_from_uri(input_uri)
            if input_action:
                self.edges.append((input_action, action))

    def get_upstream(self, action: str, depth: int = -1) -> List[str]:
        """Get all upstream actions."""
        upstream = set()
        queue = [action]
        current_depth = 0

        while queue and (depth == -1 or current_depth < depth):
            current = queue.pop(0)
            for from_action, to_action in self.edges:
                if to_action == current and from_action not in upstream:
                    upstream.add(from_action)
                    queue.append(from_action)
            current_depth += 1

        return list(upstream)

    def get_downstream(self, action: str, depth: int = -1) -> List[str]:
        """Get all downstream actions."""
        downstream = set()
        queue = [action]
        current_depth = 0

        while queue and (depth == -1 or current_depth < depth):
            current = queue.pop(0)
            for from_action, to_action in self.edges:
                if from_action == current and to_action not in downstream:
                    downstream.add(to_action)
                    queue.append(to_action)
            current_depth += 1

        return list(downstream)

    def to_ascii_tree(self, root_action: str) -> str:
        """Generate ASCII tree representation."""
        lines = [root_action]
        self._add_upstream_tree(root_action, lines, "", True)
        return "\n".join(lines)

    def _add_upstream_tree(
        self,
        action: str,
        lines: List[str],
        prefix: str,
        is_last: bool,
    ) -> None:
        """Recursively add upstream actions to tree."""
        upstream = [e[0] for e in self.edges if e[1] == action]

        for i, up_action in enumerate(upstream):
            is_last_child = i == len(upstream) - 1
            connector = "└── " if is_last_child else "├── "
            lines.append(f"{prefix}{connector}{up_action}")

            new_prefix = prefix + ("    " if is_last_child else "│   ")
            self._add_upstream_tree(up_action, lines, new_prefix, is_last_child)

    def _extract_action_from_uri(self, uri: str) -> Optional[str]:
        """Extract action name from storage URI."""
        # gs://bucket/runs/run_id/target/action_name.json
        # file:///path/target/action_name/run_id.json
        parts = uri.split("/")

        for i, part in enumerate(parts):
            if part == "target" and i + 1 < len(parts):
                action = parts[i + 1].replace(".json", "")
                return action

        return None
```

---

## Migration Path

### Phase 1: Abstraction Layer (Non-Breaking)

**Goal:** Introduce interfaces and refactor current code without changing behavior.

**Changes:**
1. Create `agent_actions/storage/` package
2. Implement `IStorageBackend` interface
3. Implement `LocalStorage` wrapping existing `FileWriter`/`UnifiedSourceDataSaver`
4. Add `StorageManager` with factory methods
5. **No breaking changes** - existing code continues to work

**Files Created:**
```
agent_actions/storage/
├── __init__.py
├── interfaces.py      # IStorageBackend
├── types.py           # StorageConfig, etc.
├── manager.py         # StorageManager
├── uri.py             # URIResolver
├── cache.py           # StorageCache
├── lineage.py         # LineageGraph
└── backends/
    ├── __init__.py
    └── local.py       # LocalStorage
```

**Files Modified:**
- `agent_actions/workflow/pipeline.py` - Use StorageManager for writes
- `agent_actions/workflow/managers/output.py` - Use StorageManager for reads

### Phase 2: Cloud Backends

**Goal:** Add cloud storage support.

**Changes:**
1. Implement `GCSStorage`
2. Implement `S3Storage`
3. Implement `AzureStorage`
4. Add storage configuration to workflow YAML schema
5. Add environment-based configuration

**Files Created:**
```
agent_actions/storage/backends/
├── gcs.py
├── s3.py
└── azure.py

config/
├── storage.local.yml
├── storage.staging.yml
└── storage.prod.yml
```

**New Dependencies (Optional):**
```
google-cloud-storage  # For GCS
boto3                 # For S3
azure-storage-blob    # For Azure
```

### Phase 3: CLI & Tooling

**Goal:** Add management commands and advanced features.

**Changes:**
1. Add `agac storage` command group
2. Add lineage tracking
3. Add migration tools
4. Add caching layer

**Files Created:**
```
agent_actions/cli/commands/storage.py
```

**CLI Commands:**
```bash
agac storage list
agac storage inspect <run_id>
agac storage export <run_id>
agac storage cleanup
agac storage lineage
agac storage migrate
```

### Phase 4: Advanced Features (Future)

**Goal:** Add enterprise features.

**Potential additions:**
1. SQLite/DuckDB backend for queryable local storage
2. Parquet/Arrow format support
3. Streaming reads/writes for large datasets
4. Schema registry integration
5. Encryption at rest
6. Multi-region support

---

## Testing Strategy

### Unit Tests

```python
# tests/storage/test_local_storage.py

class TestLocalStorage:
    def test_write_output_creates_file(self):
        """write_output creates JSON file in correct location."""

    def test_write_output_fires_events(self):
        """write_output fires FileWriteStartedEvent and FileWriteCompleteEvent."""

    def test_read_output_returns_data(self):
        """read_output returns previously written data."""

    def test_read_output_with_field_filter(self):
        """read_output with fields parameter returns filtered data."""

    def test_read_output_not_found_raises(self):
        """read_output raises DataNotFoundError when file doesn't exist."""

    def test_list_runs_returns_all_runs(self):
        """list_runs returns all runs in metadata directory."""

    def test_list_runs_with_filters(self):
        """list_runs applies workflow_name and since filters."""

    def test_delete_run_removes_all_data(self):
        """delete_run removes target, source, and metadata files."""

    def test_cleanup_removes_old_runs(self):
        """cleanup removes runs older than specified date."""

    def test_cleanup_dry_run_doesnt_delete(self):
        """cleanup with dry_run=True doesn't delete files."""

    def test_lineage_tracking_adds_metadata(self):
        """write_output with lineage_tracking adds _lineage to records."""
```

```python
# tests/storage/test_storage_manager.py

class TestStorageManager:
    def test_from_workflow_config_local(self):
        """from_workflow_config creates LocalStorage by default."""

    def test_from_workflow_config_gcs(self):
        """from_workflow_config creates GCSStorage when configured."""

    def test_from_environment_uses_env_file(self):
        """from_environment loads config from config/storage.{env}.yml."""

    def test_caching_returns_cached_data(self):
        """read_output returns cached data on second call."""

    def test_write_invalidates_cache(self):
        """write_output invalidates cache for that URI."""
```

```python
# tests/storage/test_cache.py

class TestStorageCache:
    def test_get_returns_none_when_empty(self):
        """get returns None when cache is empty."""

    def test_put_and_get_roundtrip(self):
        """put stores data, get retrieves it."""

    def test_ttl_expires_entries(self):
        """get returns None for expired entries."""

    def test_size_limit_evicts_old_entries(self):
        """put evicts old entries when cache exceeds max_size."""

    def test_invalidate_removes_entry(self):
        """invalidate removes specific entry."""

    def test_invalidate_run_removes_all_run_entries(self):
        """invalidate_run removes all entries for a run."""
```

### Integration Tests

```python
# tests/integration/test_storage_integration.py

class TestStorageIntegration:
    def test_workflow_with_local_storage(self):
        """Complete workflow execution with LocalStorage."""

    def test_workflow_with_gcs_storage(self):
        """Complete workflow execution with GCSStorage (requires GCS emulator)."""

    def test_migrate_local_to_gcs(self):
        """Migrate data from local to GCS backend."""

    def test_lineage_across_actions(self):
        """Lineage tracking captures input URIs across actions."""
```

### Parity Tests

```python
# tests/storage/test_storage_parity.py

class TestStorageParity:
    def test_local_storage_matches_current_behavior(self):
        """
        LocalStorage produces identical output to current FileWriter.

        This ensures the abstraction doesn't change existing behavior.
        """

    def test_gcs_storage_matches_local_structure(self):
        """GCSStorage data structure matches LocalStorage."""
```

---

## Backward Compatibility

### Compatible Changes

1. **Storage configuration is optional**
   - Workflows without `defaults.storage` use LocalStorage (current behavior)
   - No migration required for existing workflows

2. **LocalStorage maintains file structure**
   - `agent_io/target/`, `agent_io/source/` structure unchanged
   - Existing tools/scripts continue to work

3. **Existing events preserved**
   - `FileWriteStartedEvent`, `FileWriteCompleteEvent` still fired
   - Event listeners continue to work

### Breaking Changes

**None in Phase 1.**

**Phase 2+ potential breaking changes:**
1. If `storage.backend` is set to non-local, file paths change
   - **Migration:** Only affects workflows explicitly opting in to cloud storage

2. `_lineage` field added to output records (if `lineage_tracking: true`)
   - **Migration:** Set `lineage_tracking: false` to disable

---

## Examples

### Example 1: Local Development (Default)

No configuration needed - uses current behavior:

```yaml
# workflow.yml
name: my_workflow
actions:
  - name: process_data
    # ... action config
```

### Example 2: Cloud Production Deployment

```yaml
# workflow.yml
name: my_workflow
version: "1.0.0"

defaults:
  storage:
    backend: gcs
    config:
      gcs:
        bucket: prod-ml-workflows
        prefix: workflows/{workflow_name}/
        project: ${GCP_PROJECT_ID}
    options:
      format: json
      compression: gzip
      ttl: 90d
      lineage_tracking: true

actions:
  - name: process_data
    # Output automatically goes to:
    # gs://prod-ml-workflows/workflows/my_workflow/runs/{run_id}/target/process_data.json
```

### Example 3: Environment-Based Configuration

```yaml
# config/storage.prod.yml
storage:
  backend: gcs
  config:
    gcs:
      bucket: prod-ml-workflows
      prefix: v1/
  options:
    format: parquet
    compression: zstd
    ttl: 90d
  cache:
    enabled: false  # No caching in prod
```

```bash
# Run with production storage
AGENT_ACTIONS_ENV=prod agac run -a my_workflow
```

### Example 4: Migration Workflow

```bash
# List runs in staging
agac storage list --env staging --workflow my_workflow

# Migrate specific run to production
agac storage migrate \
  --from staging \
  --to prod \
  --workflow my_workflow \
  --run run_abc123

# Verify migration
agac storage inspect run_abc123 --env prod
```

---

## Open Questions

### 1. Streaming Support

**Question:** Should we support streaming reads/writes for large datasets that don't fit in memory?

**Options:**
- A) Add `stream_output()` and `stream_input()` methods to interface
- B) Handle streaming at a higher level (pipeline-level chunking)
- C) Defer to Phase 4

**Recommendation:** Option A for interface, implement in Phase 4

### 2. Schema Registry Integration

**Question:** Should the storage layer validate data against registered schemas?

**Options:**
- A) Integrate with existing schema validation in `agent_actions/output/response/schema.py`
- B) Add optional schema validation in storage layer
- C) Keep schema validation separate

**Recommendation:** Option C - keep concerns separated

### 3. Encryption

**Question:** Should we add client-side encryption for sensitive data?

**Options:**
- A) Add encryption option in storage configuration
- B) Rely on cloud provider encryption (GCS/S3/Azure server-side)
- C) Defer to Phase 4

**Recommendation:** Option B for Phase 2, Option A for Phase 4

### 4. Multi-Region Support

**Question:** Should we support geo-replicated storage configs?

**Options:**
- A) Add `regions` option for cloud backends
- B) Handle at infrastructure level (bucket replication)
- C) Defer

**Recommendation:** Option B - let cloud providers handle replication

### 5. Run ID Generation

**Question:** How should run IDs be generated?

**Options:**
- A) UUID (current approach)
- B) Timestamp-based (e.g., `run_20260130_143022`)
- C) Hash-based (deterministic from inputs)
- D) Configurable

**Recommendation:** Option D - allow configuration with UUID as default

---

## Summary

### What Changes

1. **New package:** `agent_actions/storage/` with pluggable backend abstraction
2. **New interface:** `IStorageBackend` with async/sync methods
3. **New configuration:** `defaults.storage` block in workflow YAML
4. **New CLI commands:** `agac storage list|inspect|export|cleanup|lineage|migrate`
5. **New feature:** Automatic lineage tracking across runs

### Benefits

| Benefit | Description |
|---------|-------------|
| **Cloud-native** | Run workflows in cloud environments without code changes |
| **Scalable** | Handle large datasets with cloud object stores |
| **Queryable** | Search and filter runs with SQLite/DB backends (Phase 4) |
| **Portable** | Move data between environments easily |
| **Auditable** | Full lineage tracking for compliance |
| **Cost-effective** | TTL and cleanup policies manage storage costs |
| **Developer-friendly** | Local files for dev, cloud for prod - same workflow |

### Migration Required

- **Phase 1:** None - existing workflows continue to work
- **Phase 2+:** Only if opting in to cloud storage

---

## Approval Checklist

- [ ] Architecture reviewed
- [ ] Interface design complete
- [ ] Backend implementations specified
- [ ] CLI commands specified
- [ ] Test strategy defined
- [ ] Migration path documented
- [ ] Backward compatibility considered
- [ ] Example configurations provided
- [ ] Open questions documented
- [ ] Implementation ready to begin

---

**End of RFC**
