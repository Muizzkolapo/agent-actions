"""Base class for content loaders."""

# import-outside-toplevel: anyio is an optional dependency with fallback behavior
# super-init-not-called: ProcessorErrorHandlerMixin doesn't require __init__ call
# unnecessary-pass: Required for abstract methods to satisfy ABC contract
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional, TypeVar, Generic

from agent_actions.configuration.interfaces import IDataLoader, ProcessingMode
from agent_actions.response_processing.config_types import AgentEntryDict
from agent_actions.utilities.processor.error_handling import ProcessorErrorHandlerMixin
from agent_actions.utilities.retry import retry

__version__ = "0.1.0"
logger = logging.getLogger(__name__)
T = TypeVar("T")


class BaseLoader(ProcessorErrorHandlerMixin, IDataLoader, ABC, Generic[T]):
    """Abstract base class for all content loaders with async support."""

    def __init__(self, agent_config: AgentEntryDict, agent_name: str):
        """Initialize with agent configuration and name.

        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.logger = logging.getLogger(__name__)

    def supports_async(self) -> bool:
        """Return True if this loader supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def load_file(self, file_path: str) -> str:
        """Safely load a file's content with retry logic."""

        @retry(max_attempts=3, delay=0.5, exceptions=(IOError, OSError))
        def _load_file() -> str:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()

        try:
            return _load_file()
        except Exception as e:
            self.handle_file_error(e, "read", file_path)
            raise

    async def load_file_async(self, file_path: str) -> str:
        """Safely load a file's content asynchronously with retry logic."""
        try:
            try:
                import anyio

                async with await anyio.open_file(file_path, "r", encoding="utf-8") as f:
                    return await f.read()
            except ImportError:
                try:
                    return await asyncio.to_thread(self.load_file, file_path)
                except AttributeError:
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, self.load_file, file_path)
        except Exception as e:
            self.handle_file_error(e, "read", file_path)
            raise

    @abstractmethod
    def process(self, content: Any, file_path: Optional[str] = None) -> T:
        """Load and parse content from a file or in-memory input.

        Args:
            content: Raw content provided directly (optional if file_path is provided).
            file_path: Path to the file to load content from.

        Returns:
            Parsed content such as a string, dictionary, or list depending on loader type.
        """
        pass

    async def process_async(self, content: Any, file_path: Optional[str] = None) -> T:
        """Async version of process method.

        Args:
            content: Raw content provided directly (optional if file_path is provided).
            file_path: Path to the file to load content from.

        Returns:
            Parsed content such as a string, dictionary, or list depending on loader type.
        """
        try:
            import anyio

            return await anyio.to_thread.run_sync(self.process, content, file_path)
        except ImportError:
            try:
                return await asyncio.to_thread(self.process, content, file_path)
            except (AttributeError, RuntimeError):
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, self.process, content, file_path)

    def load_data(self, file_path: str) -> T:
        """Implementation of IDataLoader interface."""
        content = self.load_file(file_path)
        return self.process(content, file_path)

    async def load_data_async(self, file_path: str) -> T:
        """Async implementation of IDataLoader interface."""
        content = await self.load_file_async(file_path)
        return await self.process_async(content, file_path)

    @abstractmethod
    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if this loader can handle the given file extension."""
        pass
