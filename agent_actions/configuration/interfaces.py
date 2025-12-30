"""Common interfaces for processors."""

import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, Tuple, TypeVar

# Generic type variables for interfaces
T = TypeVar("T")
DataT = TypeVar("DataT", bound=Dict[str, Any])
ContentT = TypeVar("ContentT")


class ProcessingMode(Enum):
    """Defines the processing mode for processors."""

    SYNC = "sync"
    ASYNC = "async"
    AUTO = "auto"  # Choose based on system capabilities and data size


# Base interfaces
class IAsyncCapable(ABC):  # pylint: disable=too-few-public-methods
    """Interface for components that support async operations."""

    @abstractmethod
    def supports_async(self) -> bool:
        """Return True if this component supports async operations."""

    @abstractmethod
    def get_processing_mode(self) -> ProcessingMode:
        """Return the preferred processing mode for this component."""


class ILoader(IAsyncCapable):  # pylint: disable=too-few-public-methods
    """Base interface for all loaders."""


class IProcessor(IAsyncCapable):  # pylint: disable=too-few-public-methods
    """Base interface for all processors."""


class IGenerator(IAsyncCapable):  # pylint: disable=too-few-public-methods
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
    def load_source_data(self, file_path: str) -> List[Dict]:
        """
        Load source data from the source directory.

        Args:
            file_path: Path to the file containing processed data

        Returns:
            List of source data items
        """

    async def load_source_data_async(self, file_path: str) -> List[Dict]:
        """
        Async version of load_source_data. Default implementation uses sync version.

        Args:
            file_path: Path to the file containing processed data

        Returns:
            List of source data items
        """
        return await asyncio.to_thread(self.load_source_data, file_path)

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

    @abstractmethod
    def load_source_content(self, file_path: str, context_data: Dict[str, Any]) -> Optional[Any]:
        """
        Load specific content from source file by source_guid.

        Args:
            file_path: Path to the file containing processed data
            context_data: Context data containing source_guid

        Returns:
            Optional[Any]: Loaded content or None if not found
        """

    async def load_source_content_async(
        self, file_path: str, context_data: Dict[str, Any]
    ) -> Optional[Any]:
        """
        Async version of load_source_content. Default implementation uses sync version.

        Args:
            file_path: Path to the file containing processed data
            context_data: Context data containing source_guid

        Returns:
            Optional[Any]: Loaded content or None if not found
        """
        return await asyncio.to_thread(self.load_source_content, file_path, context_data)


# Processor interfaces
class IContentProcessor(IProcessor, Generic[DataT]):
    """Interface for content processors.

    Type parameter DataT represents the type of data items being processed.
    """

    @abstractmethod
    def process(
        self, data: List[DataT], file_path: str, output_directory: Optional[str] = None
    ) -> List[DataT]:
        """Process a list of data items."""

    async def process_async(
        self, data: List[DataT], file_path: str, output_directory: Optional[str] = None
    ) -> List[DataT]:
        """
        Async version of process. Default implementation uses sync version.

        Args:
            data: List of data items to process
            file_path: Path to the input file
            output_directory: Optional output directory

        Returns:
            List of processed data items
        """
        return await asyncio.to_thread(self.process, data, file_path, output_directory)

    @abstractmethod
    def process_for_side_output(
        self, data: List[DataT], file_path: str
    ) -> Tuple[List[DataT], List[DataT]]:
        """Process data and separate into main and side outputs."""

    async def process_for_side_output_async(
        self, data: List[DataT], file_path: str
    ) -> Tuple[List[DataT], List[DataT]]:
        """
        Async version of process_for_side_output. Default implementation.

        Args:
            data: List of data items to process
            file_path: Path to the input file

        Returns:
            Tuple of (main_output, side_output) lists
        """
        return await asyncio.to_thread(self.process_for_side_output, data, file_path)


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
