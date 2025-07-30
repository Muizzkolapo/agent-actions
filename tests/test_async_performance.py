"""Performance tests for async processing standardization."""
import asyncio
import time
import pytest
from typing import List, Dict
from unittest.mock import Mock, AsyncMock

from agent_actions.processors.interfaces import ProcessingMode
from agent_actions.processors.base_async_processor import BaseAsyncProcessor, ProcessingContext


class MockAsyncProcessor(BaseAsyncProcessor):
    """Mock processor for testing async patterns."""
    
    def __init__(self, processing_delay: float = 0.1, **kwargs):
        super().__init__(**kwargs)
        self.processing_delay = processing_delay
        self.processed_items = []
    
    async def _process_single_item_async(self, item: Dict, *args, **kwargs) -> Dict:
        """Mock async processing with delay."""
        await asyncio.sleep(self.processing_delay)
        processed_item = {"original": item, "processed": True, "timestamp": time.time()}
        self.processed_items.append(processed_item)
        return processed_item


class TestAsyncProcessingPerformance:
    """Test suite for async processing performance."""
    
    @pytest.fixture
    def mock_data(self):
        """Generate mock data for testing."""
        return [{"id": i, "content": f"item_{i}"} for i in range(10)]
    
    @pytest.fixture
    def processor(self):
        """Create a mock async processor."""
        return MockAsyncProcessor(processing_delay=0.01)
    
    def test_processing_mode_enum(self):
        """Test ProcessingMode enum values."""
        assert ProcessingMode.SYNC.value == "sync"
        assert ProcessingMode.ASYNC.value == "async"
        assert ProcessingMode.AUTO.value == "auto"
    
    def test_processor_async_capabilities(self, processor):
        """Test that processor reports async capabilities correctly."""
        assert processor.supports_async() is True
        assert processor.get_processing_mode() == ProcessingMode.ASYNC
    
    @pytest.mark.asyncio
    async def test_parallel_processing_performance(self, processor, mock_data):
        """Test that parallel processing is faster than sequential."""
        # Test parallel processing
        start_time = time.time()
        parallel_results = await processor.process_items_parallel(
            mock_data, 
            processor._process_single_item_async
        )
        parallel_time = time.time() - start_time
        
        # Reset processor state
        processor.processed_items.clear()
        
        # Test sequential processing
        start_time = time.time()
        sequential_results = await processor.process_items_sequential(
            mock_data, 
            processor._process_single_item_async
        )
        sequential_time = time.time() - start_time
        
        # Assertions
        assert len(parallel_results) == len(mock_data)
        assert len(sequential_results) == len(mock_data)
        assert parallel_time < sequential_time  # Parallel should be faster
        
        # Results should be equivalent (though order might differ for parallel)
        parallel_ids = {result["original"]["id"] for result in parallel_results}
        sequential_ids = {result["original"]["id"] for result in sequential_results}
        assert parallel_ids == sequential_ids
    
    @pytest.mark.asyncio
    async def test_concurrency_limiting(self, mock_data):
        """Test that concurrency limiting works correctly."""
        # Create processor with concurrency limit
        limited_processor = MockAsyncProcessor(
            processing_delay=0.01, 
            concurrency_limit=3
        )
        
        # Track active concurrent operations
        active_count = 0
        max_concurrent = 0
        
        original_process = limited_processor._process_single_item_async
        
        async def tracked_process(item, *args, **kwargs):
            nonlocal active_count, max_concurrent
            active_count += 1
            max_concurrent = max(max_concurrent, active_count)
            try:
                result = await original_process(item, *args, **kwargs)
                return result
            finally:
                active_count -= 1
        
        limited_processor._process_single_item_async = tracked_process
        
        # Process items with concurrency limit
        results = await limited_processor.process_items_parallel(
            mock_data,
            limited_processor._process_single_item_async
        )
        
        # Assertions
        assert len(results) == len(mock_data)
        assert max_concurrent <= 3  # Should not exceed concurrency limit
        assert max_concurrent > 0   # Should have processed concurrently
    
    def test_processing_context_auto_mode(self):
        """Test ProcessingContext auto mode decision logic."""
        context = ProcessingContext(mode=ProcessingMode.AUTO)
        
        # Small dataset should prefer sync
        assert context.should_use_async(data_size=5) is False
        
        # Large dataset should prefer async
        assert context.should_use_async(data_size=20) is True
        
        # Any size with concurrency limit should use async
        context_with_limit = ProcessingContext(
            mode=ProcessingMode.AUTO, 
            concurrency_limit=5
        )
        assert context_with_limit.should_use_async(data_size=1) is True
    
    def test_processing_context_explicit_modes(self):
        """Test ProcessingContext explicit mode settings."""
        sync_context = ProcessingContext(mode=ProcessingMode.SYNC)
        async_context = ProcessingContext(mode=ProcessingMode.ASYNC)
        
        # Explicit modes should override auto-detection
        assert sync_context.should_use_async(data_size=100) is False
        assert async_context.should_use_async(data_size=1) is True
    
    @pytest.mark.asyncio
    async def test_async_file_operations(self, processor, tmp_path):
        """Test async file I/O operations."""
        # Create test file
        test_file = tmp_path / "test_async.txt"
        test_content = "This is test content for async operations."
        
        # Write file asynchronously
        await processor.write_file_async(str(test_file), test_content)
        
        # Verify file was created
        assert test_file.exists()
        
        # Read file asynchronously
        read_content = await processor.read_file_async(str(test_file))
        
        # Verify content matches
        assert read_content == test_content
    
    @pytest.mark.asyncio
    async def test_error_handling_in_parallel_processing(self, mock_data):
        """Test error handling during parallel processing."""
        class FailingProcessor(MockAsyncProcessor):
            async def _process_single_item_async(self, item, *args, **kwargs):
                if item["id"] == 5:  # Fail on specific item
                    raise ValueError(f"Simulated error for item {item['id']}")
                return await super()._process_single_item_async(item, *args, **kwargs)
        
        failing_processor = FailingProcessor(processing_delay=0.01)
        
        # Processing should raise exception due to failing item
        with pytest.raises(ValueError, match="Simulated error for item 5"):
            await failing_processor.process_items_parallel(
                mock_data,
                failing_processor._process_single_item_async
            )


class TestAsyncInterfaceCompatibility:
    """Test compatibility between sync and async interfaces."""
    
    def test_interface_methods_exist(self):
        """Test that all required async methods exist in interfaces."""
        from agent_actions.processors.interfaces import (
            IContentProcessor, IDataProcessor, IDataGenerator, IDataLoader, ISourceDataLoader
        )
        
        # Test that async methods exist
        assert hasattr(IContentProcessor, 'process_async')
        assert hasattr(IContentProcessor, 'process_for_side_output_async')
        assert hasattr(IDataProcessor, 'process_item_async')
        assert hasattr(IDataGenerator, 'create_agent_with_data_async')
        assert hasattr(IDataLoader, 'load_data_async')
        assert hasattr(ISourceDataLoader, 'load_source_data_async')
        assert hasattr(ISourceDataLoader, 'save_source_data_async')
        assert hasattr(ISourceDataLoader, 'load_source_content_async')
    
    @pytest.mark.asyncio
    async def test_default_async_implementations(self):
        """Test that default async implementations work correctly."""
        from agent_actions.processors.interfaces import IDataLoader
        
        class MockSyncLoader(IDataLoader):
            def supports_async(self):
                return True
            
            def get_processing_mode(self):
                return ProcessingMode.AUTO
            
            def load_data(self, file_path: str):
                return [{"file": file_path, "loaded": True}]
        
        loader = MockSyncLoader()
        
        # Test async method falls back to sync
        result = await loader.load_data_async("test_file.txt")
        expected = [{"file": "test_file.txt", "loaded": True}]
        assert result == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])