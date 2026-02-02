"""Module for loading source data from storage backend."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agent_actions.config.interfaces import ISourceDataLoader, ProcessingMode
from agent_actions.errors import DependencyError

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class SourceDataLoader(ISourceDataLoader):
    """Handles loading source data from storage backend."""

    def __init__(
        self,
        agent_name: str,
        storage_backend: "StorageBackend",
    ):
        """
        Initialize the source data loader.

        Args:
            agent_name: Name of the agent
            storage_backend: Storage backend for database-backed reads (required)

        Raises:
            DependencyError: If storage_backend is not provided
        """
        self.agent_name = agent_name
        if storage_backend is None:
            raise DependencyError("SourceDataLoader", "storage_backend")
        self.storage_backend = storage_backend

    def supports_async(self) -> bool:
        """Return True as this loader supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def load_source_data(
        self, file_path: str, source_relative_path: Optional[str] = None
    ) -> List[Dict]:
        """
        Load source data from the storage backend.

        Args:
            file_path: Path to the file (used to derive relative path if not provided)
            source_relative_path: Optional explicit relative path for backend lookup.

        Returns:
            List of source data items

        Raises:
            FileNotFoundError: If source data not found in backend
        """
        # Use explicit path if provided, otherwise derive from file_path
        relative_path = source_relative_path or self._derive_source_relative_path(file_path)

        if not relative_path:
            raise FileNotFoundError(f"Could not derive source path from: {file_path}")

        logger.debug(
            "Loading source data from backend: %s",
            relative_path,
            extra={"agent_name": self.agent_name},
        )
        return self.storage_backend.read_source(relative_path)

    def _derive_source_relative_path(self, file_path: str) -> Optional[str]:
        """
        Derive the relative path for source data from a file path.

        Args:
            file_path: Path to the file

        Returns:
            Relative path suitable for backend lookup, or None if derivation fails
        """
        try:
            path = Path(file_path)
            # Use the filename stem as the relative path
            filename = path.stem  # filename without extension
            if filename:
                return filename
        except Exception as e:
            logger.debug("Could not derive relative path: %s", e)
        return None

    def save_source_data(self, relative_path: str, data: List[Dict]) -> None:
        """
        Save source data to the storage backend.

        Args:
            relative_path: Relative path for the source data
            data: List of source data items to save
        """
        logger.debug(
            "Saving source data to backend: %s",
            relative_path,
            extra={"agent_name": self.agent_name},
        )
        self.storage_backend.write_source(relative_path, data)

    def load_source_content(self, file_path: str, context_data: Dict[str, Any]) -> Optional[Any]:
        """
        Load specific content from source by source_guid.

        Args:
            file_path: Path to derive source location
            context_data: Context data containing source_guid

        Returns:
            Optional[Any]: Loaded content or None if not found
        """
        source_guid = context_data.get("source_guid")
        if not source_guid:
            return None

        source_data = self.load_source_data(file_path)
        for item in source_data:
            if item.get("source_guid") == source_guid:
                # Support both legacy wrapped content and new flat content
                if "content" in item and isinstance(item["content"], dict):
                    return item.get("content")
                return item
        return None
