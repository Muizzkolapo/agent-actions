"""Common interfaces for processors."""

import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Generic, TypeVar

# Generic type variable for interfaces
T = TypeVar("T")


class ProcessingMode(Enum):
    """Execution strategy for individual components (loaders, processors, generators).

    This enum controls *how* a single component runs: synchronously, asynchronously,
    or auto-detected.  Values: SYNC, ASYNC, AUTO.

    Not to be confused with ``processing.types.ProcessingMode`` which controls the
    *pipeline-level* dispatch mode (ONLINE vs BATCH).
    """

    SYNC = "sync"
    ASYNC = "async"
    AUTO = "auto"  # Choose based on system capabilities and data size


# Base interfaces
class IAsyncCapable(ABC):
    """Interface for components that support async operations."""

    @abstractmethod
    def supports_async(self) -> bool:
        """Return True if this component supports async operations."""

    @abstractmethod
    def get_processing_mode(self) -> ProcessingMode:
        """Return the preferred processing mode for this component."""


class ILoader(IAsyncCapable):
    """Base interface for all loaders."""


class IProcessor(IAsyncCapable):
    """Base interface for all processors."""


class IGenerator(IAsyncCapable):
    """Base interface for all generators."""


# Loader interfaces
class IDataLoader(ILoader, Generic[T]):
    """Interface for data loading operations."""

    @abstractmethod
    def load_data(self, file_path: str) -> T:
        """Load data from the given file path."""

    async def load_data_async(self, file_path: str) -> T:
        """Async version of load_data."""
        return await asyncio.to_thread(self.load_data, file_path)


class ISourceDataLoader(ILoader):
    """Interface for source data loading operations."""

    @abstractmethod
    def load_source_data(self, source_relative_path: str) -> list[dict]:
        """Load source data from the storage backend."""

    async def load_source_data_async(self, source_relative_path: str) -> list[dict]:
        """Async version of load_source_data."""
        return await asyncio.to_thread(self.load_source_data, source_relative_path)

    @abstractmethod
    def save_source_data(self, relative_path: str, data: list[dict]) -> None:
        """Save source data to the storage backend."""

    async def save_source_data_async(self, relative_path: str, data: list[dict]) -> None:
        """Async version of save_source_data."""
        return await asyncio.to_thread(self.save_source_data, relative_path, data)


# Processor interfaces
class IDataProcessor(IProcessor):
    """Interface for data processing."""

    @abstractmethod
    def process_item(
        self,
        contents: dict,
        generated_data: list[dict],
        source_guid: str,
        passthrough_fields: dict | None = None,
    ) -> list[dict]:
        """Process a single data item."""

    async def process_item_async(
        self,
        contents: dict,
        generated_data: list[dict],
        source_guid: str,
        passthrough_fields: dict | None = None,
    ) -> list[dict]:
        """Async version of process_item."""
        return await asyncio.to_thread(
            self.process_item, contents, generated_data, source_guid, passthrough_fields
        )
