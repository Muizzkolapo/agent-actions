"""Source data loading from storage backend."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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
        storage_backend: StorageBackend,
    ):
        self.agent_name = agent_name
        if storage_backend is None:
            raise DependencyError("SourceDataLoader", "storage_backend")
        self.storage_backend = storage_backend

    def supports_async(self) -> bool:
        """Return True as this loader supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode."""
        return ProcessingMode.AUTO

    def load_source_data(self, source_relative_path: str) -> list[dict]:
        """Load source data from the storage backend."""
        logger.debug(
            "Loading source data from backend: %s",
            source_relative_path,
            extra={"agent_name": self.agent_name},
        )
        return self.storage_backend.read_source(source_relative_path)

    def save_source_data(self, relative_path: str, data: list[dict]) -> None:
        """Save source data to the storage backend."""
        logger.debug(
            "Saving source data to backend: %s",
            relative_path,
            extra={"agent_name": self.agent_name},
        )
        self.storage_backend.write_source(relative_path, data)
