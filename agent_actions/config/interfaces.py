"""Common interfaces for processors."""

import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

# Generic type variable for interfaces
T = TypeVar("T")


class ProcessingMode(Enum):
    """Defines the processing mode for processors."""

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
    """Interface for data loading operations.

    Type parameter T represents the type of data returned by load_data.
    Default is List[Dict[str, Any]] for backward compatibility.
    """

    @abstractmethod
    def load_data(self, file_path: str) -> T:
        """
        Load data from the given file path.

        Args:
            file_path: The path to the data file.

        Returns:
            A list of dictionaries, where each dictionary represents a row of data.
        """

    async def load_data_async(self, file_path: str) -> T:
        """
        Async version of load_data. Default implementation uses sync version.

        Args:
            file_path: The path to the data file.

        Returns:
            A list of dictionaries, where each dictionary represents a row of data.
        """
        return await asyncio.to_thread(self.load_data, file_path)


class ISourceDataLoader(ILoader):
    """Interface for source data loading operations."""

    @abstractmethod
    def load_source_data(self, source_relative_path: str) -> List[Dict]:
        """
        Load source data from the storage backend.

        Args:
            source_relative_path: Relative path for backend lookup (required)

        Returns:
            List of source data items
        """

    async def load_source_data_async(self, source_relative_path: str) -> List[Dict]:
        """
        Async version of load_source_data. Default implementation uses sync version.

        Args:
            source_relative_path: Relative path for backend lookup (required)

        Returns:
            List of source data items
        """
        return await asyncio.to_thread(self.load_source_data, source_relative_path)

    @abstractmethod
    def save_source_data(self, file_path: str, source_guid: str, content: Dict) -> None:
        """
        Save source data to the source directory.

        Args:
            file_path: Path to the file containing processed data
            source_guid: source_guid to associate with the content
            content: Content to save
        """

    async def save_source_data_async(self, file_path: str, source_guid: str, content: Dict) -> None:
        """
        Async version of save_source_data. Default implementation uses sync version.

        Args:
            file_path: Path to the file containing processed data
            source_guid: source_guid to associate with the content
            content: Content to save
        """
        return await asyncio.to_thread(self.save_source_data, file_path, source_guid, content)


# Processor interfaces
class IDataProcessor(IProcessor):
    """Interface for data processing."""

    @abstractmethod
    def process_item(
        self,
        contents: Dict,
        generated_data: List[Dict],
        source_guid: str,
        passthrough_fields: Optional[Dict] = None,
    ) -> List[Dict]:
        """Process a single data item."""

    async def process_item_async(
        self,
        contents: Dict,
        generated_data: List[Dict],
        source_guid: str,
        passthrough_fields: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Async version of process_item. Default implementation uses sync version.

        Args:
            contents: Content data to process
            generated_data: Previously generated data
            source_guid: Source identifier
            passthrough_fields: Optional fields to merge into output

        Returns:
            List of processed data items
        """
        return await asyncio.to_thread(
            self.process_item, contents, generated_data, source_guid, passthrough_fields
        )
