"""Abstract storage backend interface for extensible data persistence."""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class StorageBackend(ABC):
    """
    Abstract base class for storage backends.

    This interface defines the contract for storage implementations,
    enabling pluggable backends (SQLite, S3, DuckDB, etc.) while
    keeping the workflow code backend-agnostic.

    Storage backends handle:
    - Source data: Input records with source_guid for deduplication
    - Target data: Output records organized by node_name

    File paths are relative to the workflow's agent_io directory,
    maintaining compatibility with the existing JSON file structure.
    """

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """
        Return the backend type identifier.

        Returns:
            str: Backend type (e.g., 'sqlite', 's3', 'duckdb')
        """
        ...

    @abstractmethod
    def initialize(self) -> None:
        """
        Initialize the storage backend.

        This method should create any necessary tables, indexes,
        or other infrastructure required by the backend.

        Raises:
            StorageError: If initialization fails
        """
        ...

    @abstractmethod
    def write_target(
        self, node_name: str, relative_path: str, data: List[Dict[str, Any]]
    ) -> str:
        """
        Write target data for a specific node.

        Args:
            node_name: Name of the processing node (action)
            relative_path: Relative path within the target directory
            data: List of records to write

        Returns:
            str: Identifier or path for the written data

        Raises:
            StorageError: If write fails
        """
        ...

    @abstractmethod
    def read_target(
        self, node_name: str, relative_path: str
    ) -> List[Dict[str, Any]]:
        """
        Read target data for a specific node.

        Args:
            node_name: Name of the processing node (action)
            relative_path: Relative path within the target directory

        Returns:
            List of records from the target data

        Raises:
            StorageError: If read fails
            FileNotFoundError: If the target data doesn't exist
        """
        ...

    @abstractmethod
    def write_source(
        self,
        relative_path: str,
        data: List[Dict[str, Any]],
        enable_deduplication: bool = True,
    ) -> str:
        """
        Write source data with optional deduplication.

        Source data is deduplicated by source_guid when enabled,
        preventing duplicate records from being stored.

        Args:
            relative_path: Relative path within the source directory
            data: List of source records (each should have source_guid)
            enable_deduplication: If True, skip records with existing source_guids

        Returns:
            str: Identifier or path for the written data

        Raises:
            StorageError: If write fails
        """
        ...

    @abstractmethod
    def read_source(self, relative_path: str) -> List[Dict[str, Any]]:
        """
        Read source data.

        Args:
            relative_path: Relative path within the source directory

        Returns:
            List of source records

        Raises:
            StorageError: If read fails
            FileNotFoundError: If the source data doesn't exist
        """
        ...

    @abstractmethod
    def list_target_files(self, node_name: str) -> List[str]:
        """
        List all target files for a specific node.

        Args:
            node_name: Name of the processing node

        Returns:
            List of relative paths for target data entries
        """
        ...

    @abstractmethod
    def list_source_files(self) -> List[str]:
        """
        List all source files.

        Returns:
            List of relative paths for source data entries
        """
        ...

    @abstractmethod
    def preview_target(
        self,
        node_name: str,
        limit: int = 10,
        offset: int = 0,
        relative_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Preview target data for a node with pagination.

        Args:
            node_name: Name of the processing node (action)
            limit: Maximum number of records to return
            offset: Number of records to skip
            relative_path: Optional specific file to preview

        Returns:
            Dict with:
                - records: List of data records
                - total_count: Total number of records
                - node_name: The node name
                - files: List of file paths for this node
        """
        ...

    @abstractmethod
    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dict with:
                - db_path: Path to the database
                - db_size_bytes: Size of database file
                - source_count: Number of source records
                - target_count: Number of target records
                - nodes: Dict of node_name -> record_count
        """
        ...

    def close(self) -> None:
        """
        Close the storage backend and release resources.

        Override this method if the backend needs cleanup
        (e.g., closing database connections).
        """
        pass

    def __enter__(self) -> "StorageBackend":
        """Context manager entry."""
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        """Context manager exit - ensures cleanup."""
        self.close()
