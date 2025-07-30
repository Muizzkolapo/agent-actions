"""Base async processor implementation with proper async patterns."""
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any, Tuple
from .interfaces import ProcessingMode, IAsyncCapable


class BaseAsyncProcessor(IAsyncCapable):
    """
    Base class providing standardized async processing patterns.
    
    This class provides proper async implementations that avoid inefficient
    sync-to-async wrapping patterns. Subclasses should implement true async
    methods rather than wrapping synchronous operations.
    """
    
    def __init__(self, concurrency_limit: Optional[int] = None):
        """
        Initialize the async processor.
        
        Args:
            concurrency_limit: Maximum number of concurrent operations (None for unlimited)
        """
        self.concurrency_limit = concurrency_limit
        self._semaphore = asyncio.Semaphore(concurrency_limit) if concurrency_limit else None
    
    def supports_async(self) -> bool:
        """Return True as this is an async-capable processor."""
        return True
    
    def get_processing_mode(self) -> ProcessingMode:
        """Return ASYNC as the preferred processing mode."""
        return ProcessingMode.ASYNC
    
    async def process_items_parallel(
        self, 
        items: List[Any], 
        process_func: callable,
        *args, 
        **kwargs
    ) -> List[Any]:
        """
        Process multiple items in parallel with proper concurrency control.
        
        Args:
            items: List of items to process
            process_func: Async function to process each item
            *args: Additional arguments to pass to process_func
            **kwargs: Additional keyword arguments to pass to process_func
            
        Returns:
            List of processed results
        """
        async def process_with_semaphore(item):
            if self._semaphore:
                async with self._semaphore:
                    return await process_func(item, *args, **kwargs)
            else:
                return await process_func(item, *args, **kwargs)
        
        tasks = [process_with_semaphore(item) for item in items]
        return await asyncio.gather(*tasks, return_exceptions=False)
    
    async def process_items_sequential(
        self, 
        items: List[Any], 
        process_func: callable,
        *args, 
        **kwargs
    ) -> List[Any]:
        """
        Process items sequentially (useful for order-dependent operations).
        
        Args:
            items: List of items to process
            process_func: Async function to process each item
            *args: Additional arguments to pass to process_func
            **kwargs: Additional keyword arguments to pass to process_func
            
        Returns:
            List of processed results
        """
        results = []
        for item in items:
            result = await process_func(item, *args, **kwargs)
            results.append(result)
        return results
    
    async def read_file_async(self, file_path: str) -> str:
        """
        Read file content asynchronously using proper async I/O.
        
        Args:
            file_path: Path to the file to read
            
        Returns:
            File content as string
        """
        import aiofiles
        
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                return await f.read()
        except ImportError:
            # Fallback to asyncio.to_thread if aiofiles not available
            import asyncio
            def _read_file():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            return await asyncio.to_thread(_read_file)
    
    async def write_file_async(self, file_path: str, content: str) -> None:
        """
        Write file content asynchronously using proper async I/O.
        
        Args:
            file_path: Path to the file to write
            content: Content to write
        """
        import aiofiles
        
        try:
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(content)
        except ImportError:
            # Fallback to asyncio.to_thread if aiofiles not available
            import asyncio
            def _write_file():
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            await asyncio.to_thread(_write_file)
    
    @abstractmethod
    async def _process_single_item_async(self, item: Any, *args, **kwargs) -> Any:
        """
        Process a single item asynchronously. Must be implemented by subclasses.
        
        This method should contain the core async processing logic without
        using asyncio.to_thread() wrapping of synchronous operations.
        """
        pass


class AsyncProcessorMixin:
    """
    Mixin to add async capabilities to existing processors.
    
    This provides a transition path for processors that need to maintain
    backward compatibility while adding async support.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._async_processor = None
    
    def supports_async(self) -> bool:
        """Return True if async capabilities are enabled."""
        return hasattr(self, '_async_processor') and self._async_processor is not None
    
    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO to let the system choose based on context."""
        return ProcessingMode.AUTO
    
    def enable_async(self, concurrency_limit: Optional[int] = None):
        """Enable async processing capabilities."""
        if not hasattr(self, '_async_processor') or self._async_processor is None:
            self._async_processor = BaseAsyncProcessor(concurrency_limit)
    
    async def _ensure_async_enabled(self):
        """Ensure async capabilities are enabled before use."""
        if not self.supports_async():
            self.enable_async()


class ProcessingContext:
    """Context for managing processing state and configuration."""
    
    def __init__(
        self,
        mode: ProcessingMode = ProcessingMode.AUTO,
        concurrency_limit: Optional[int] = None,
        timeout: Optional[float] = None,
        retry_count: int = 0
    ):
        self.mode = mode
        self.concurrency_limit = concurrency_limit
        self.timeout = timeout
        self.retry_count = retry_count
    
    def should_use_async(self, data_size: int = 0) -> bool:
        """
        Determine if async processing should be used based on context.
        
        Args:
            data_size: Size of data to process (for AUTO mode decision)
            
        Returns:
            True if async processing should be used
        """
        if self.mode == ProcessingMode.SYNC:
            return False
        elif self.mode == ProcessingMode.ASYNC:
            return True
        else:  # AUTO mode
            # Use async for larger datasets or when concurrency limit is set
            return data_size > 10 or self.concurrency_limit is not None