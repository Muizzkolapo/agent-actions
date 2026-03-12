"""Abstract storage backend interface for extensible data persistence."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Dict, List, Any, Optional, Type

NODE_LEVEL_RECORD_ID = "__node__"
"""Sentinel record_id for node-level disposition signals."""
DISPOSITION_PASSTHROUGH = "passthrough"
DISPOSITION_SKIPPED = "skipped"
DISPOSITION_FILTERED = "filtered"
DISPOSITION_EXHAUSTED = "exhausted"
DISPOSITION_FAILED = "failed"
DISPOSITION_UNPROCESSED = "unprocessed"

VALID_DISPOSITIONS = frozenset(
    {
        DISPOSITION_PASSTHROUGH,
        DISPOSITION_SKIPPED,
        DISPOSITION_FILTERED,
        DISPOSITION_EXHAUSTED,
        DISPOSITION_FAILED,
        DISPOSITION_UNPROCESSED,
    }
)


class StorageBackend(ABC):
    """Abstract interface for pluggable storage backends (SQLite, S3, DuckDB, etc.)."""

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Return the backend type identifier."""
        ...

    @abstractmethod
    def initialize(self) -> None:
        """Create tables, indexes, and other infrastructure required by the backend."""
        ...

    @abstractmethod
    def write_target(self, action_name: str, relative_path: str, data: List[Dict[str, Any]]) -> str:
        """Write target data for a specific node."""
        ...

    @abstractmethod
    def read_target(self, action_name: str, relative_path: str) -> List[Dict[str, Any]]:
        """Read target data for a specific node.

        Raises:
            FileNotFoundError: If the target data doesn't exist.
        """
        ...

    @abstractmethod
    def write_source(
        self,
        relative_path: str,
        data: List[Dict[str, Any]],
        enable_deduplication: bool = True,
    ) -> str:
        """Write source data with optional deduplication by source_guid."""
        ...

    @abstractmethod
    def read_source(self, relative_path: str) -> List[Dict[str, Any]]:
        """Read source data.

        Raises:
            FileNotFoundError: If the source data doesn't exist.
        """
        ...

    @abstractmethod
    def list_target_files(self, action_name: str) -> List[str]:
        """List all target file paths for a specific node."""
        ...

    @abstractmethod
    def list_source_files(self) -> List[str]:
        """List all source file paths."""
        ...

    @abstractmethod
    def preview_target(
        self,
        action_name: str,
        limit: int = 10,
        offset: int = 0,
        relative_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Preview target data for a node with pagination."""
        ...

    @abstractmethod
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics (record counts, DB size, per-node breakdown)."""
        ...

    def set_disposition(
        self,
        action_name: str,
        record_id: str,
        disposition: str,
        reason: Optional[str] = None,
        relative_path: Optional[str] = None,
    ) -> None:
        """Write a disposition record (use NODE_LEVEL_RECORD_ID for node-level signals)."""
        # No-op: subclass must override to persist dispositions.

    def get_disposition(
        self,
        action_name: str,
        record_id: Optional[str] = None,
        disposition: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query disposition records with optional filters."""
        return []

    def has_disposition(
        self,
        action_name: str,
        disposition: str,
        record_id: Optional[str] = None,
    ) -> bool:
        """Check whether at least one matching disposition exists."""
        return False

    def clear_disposition(
        self,
        action_name: str,
        disposition: Optional[str] = None,
        record_id: Optional[str] = None,
    ) -> int:
        """Delete matching disposition records. Returns count deleted."""
        return 0

    def close(self) -> None:
        """Close the storage backend and release resources."""
        pass

    def __enter__(self) -> "StorageBackend":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        _exc_type: Optional[Type[BaseException]],
        _exc_val: Optional[BaseException],
        _exc_tb: Optional[TracebackType],
    ) -> None:
        """Context manager exit - ensures cleanup."""
        self.close()
