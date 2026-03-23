"""Base class for content loaders."""

# super-init-not-called: ProcessorErrorHandlerMixin doesn't require __init__ call
# unnecessary-pass: Required for abstract methods to satisfy ABC contract
import asyncio
import functools
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from agent_actions.config.interfaces import IDataLoader, ProcessingMode
from agent_actions.config.types import ActionEntryDict
from agent_actions.processing.error_handling import ProcessorErrorHandlerMixin


def retry(
    max_attempts: int = 3,
    delay: float = 0.5,
    exceptions: tuple[type[Exception], ...] = (Exception,),
):
    """Simple retry decorator for file operations."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if max_attempts < 1:
                return func(*args, **kwargs)
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        time.sleep(delay * (attempt + 1))
            assert last_exception is not None  # loop only continues on exception
            raise last_exception

        return wrapper

    return decorator


logger = logging.getLogger(__name__)
T = TypeVar("T")


@retry(max_attempts=3, delay=0.5, exceptions=(IOError, OSError))
def read_file_with_retry(file_path: str) -> str:
    """Read a file's content with automatic retry on I/O errors.

    Extracted as a module-level function so that callers that cannot
    inherit ``BaseLoader`` (e.g. ``BatchDataLoader``) can still reuse
    the retry-wrapped file reading logic.
    """
    with open(file_path, encoding="utf-8") as f:
        return f.read()


class BaseLoader(ProcessorErrorHandlerMixin, IDataLoader, ABC, Generic[T]):
    """Abstract base class for all content loaders with async support."""

    def __init__(self, agent_config: ActionEntryDict | dict[str, Any], agent_name: str):
        """Initialize with agent configuration and name."""
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.logger = logging.getLogger(__name__)

    def supports_async(self) -> bool:
        """Return True if this loader supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode."""
        return ProcessingMode.AUTO

    def load_file(self, file_path: str) -> str:
        """Safely load a file's content with retry logic."""
        try:
            return read_file_with_retry(file_path)
        except Exception as e:
            self.handle_file_error(e, "read", file_path)
            raise

    async def load_file_async(self, file_path: str) -> str:
        """Safely load a file's content asynchronously.

        Note: unlike the sync load_file(), this path does not retry on IOError/OSError.
        Use load_file() via asyncio.to_thread() if retry behavior is required.
        """
        import aiofiles  # type: ignore[import-untyped]

        try:
            async with aiofiles.open(file_path, encoding="utf-8") as f:
                return str(await f.read())
        except Exception as e:
            self.handle_file_error(e, "read", file_path)
            raise

    @abstractmethod
    def process(self, content: Any, file_path: str | None = None) -> T:
        """Load and parse content from a file or in-memory input."""
        pass

    async def process_async(self, content: Any, file_path: str | None = None) -> T:
        """Async version of process method."""
        return await asyncio.to_thread(self.process, content, file_path)

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
