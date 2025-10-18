"""
Tests for ProcessorUtils thread safety, specifically the loop correlation ID race condition fix.
"""

import threading
import time
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Set, List

from agent_actions.core.utils.processor_utils import ProcessorUtils


class TestProcessorUtilsThreadSafety:
    """Test suite for ProcessorUtils thread safety."""

    @classmethod
    def get_test_session_id(cls) -> str:
        """Get a consistent session ID for testing."""
        return "test_session_12345"

    def setup_method(self):
        """Clear the registry before each test."""
        ProcessorUtils.clear_loop_correlation_registry()

    def teardown_method(self):
        """Clear the registry after each test."""
        ProcessorUtils.clear_loop_correlation_registry()

    def test_concurrent_loop_correlation_id_generation_consistency(self):
        """Test that concurrent access generates consistent correlation IDs."""
        source_guid = "test-guid-123"
        loop_base_name = "generate_distractors"
        num_threads = 50
        num_calls_per_thread = 10
        
        correlation_ids: List[str] = []
        correlation_ids_lock = threading.Lock()
        
        def worker():
            """Worker function that generates correlation IDs."""
            local_ids = []
            for _ in range(num_calls_per_thread):
                correlation_id = ProcessorUtils.get_or_create_loop_correlation_id(
                    source_guid, loop_base_name, self.get_test_session_id()
                )
                local_ids.append(correlation_id)
                # Add small delay to increase chance of race condition
                time.sleep(0.001)
            
            with correlation_ids_lock:
                correlation_ids.extend(local_ids)
        
        # Start multiple threads
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All correlation IDs should be identical
        unique_ids = set(correlation_ids)
        assert len(unique_ids) == 1, f"Expected 1 unique ID, got {len(unique_ids)}: {unique_ids}"
        assert len(correlation_ids) == num_threads * num_calls_per_thread

    def test_concurrent_position_based_correlation_id_consistency(self):
        """Test that position-based correlation IDs are consistent across threads."""
        record_index = 42
        loop_base_name = "process_items"
        file_context = "test_file.json"
        num_threads = 30
        
        correlation_ids: List[str] = []
        correlation_ids_lock = threading.Lock()
        
        def worker():
            """Worker function that generates position-based correlation IDs."""
            correlation_id = ProcessorUtils.get_or_create_position_based_loop_correlation_id(
                record_index, loop_base_name, self.get_test_session_id(), file_context
            )
            with correlation_ids_lock:
                correlation_ids.append(correlation_id)
        
        # Start multiple threads
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All correlation IDs should be identical
        unique_ids = set(correlation_ids)
        assert len(unique_ids) == 1, f"Expected 1 unique ID, got {len(unique_ids)}: {unique_ids}"

    def test_concurrent_different_keys_generate_different_ids(self):
        """Test that different keys generate different correlation IDs even under concurrency."""
        loop_base_name = "test_loop"
        num_different_guids = 10
        num_threads_per_guid = 5
        
        all_results = {}
        results_lock = threading.Lock()
        
        def worker(source_guid: str):
            """Worker function for a specific source_guid."""
            correlation_id = ProcessorUtils.get_or_create_loop_correlation_id(
                source_guid, loop_base_name, self.get_test_session_id()
            )
            with results_lock:
                if source_guid not in all_results:
                    all_results[source_guid] = []
                all_results[source_guid].append(correlation_id)
        
        # Start multiple threads for each source_guid
        threads = []
        for i in range(num_different_guids):
            source_guid = f"guid-{i}"
            for _ in range(num_threads_per_guid):
                thread = threading.Thread(target=worker, args=(source_guid,))
                threads.append(thread)
                thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Each source_guid should have consistent correlation IDs
        assert len(all_results) == num_different_guids
        
        all_unique_ids = set()
        for source_guid, ids in all_results.items():
            # All IDs for this source_guid should be the same
            unique_ids_for_guid = set(ids)
            assert len(unique_ids_for_guid) == 1, f"Source {source_guid} has inconsistent IDs: {unique_ids_for_guid}"
            
            # Each source_guid should have a different correlation ID
            correlation_id = list(unique_ids_for_guid)[0]
            assert correlation_id not in all_unique_ids, f"Duplicate correlation ID {correlation_id}"
            all_unique_ids.add(correlation_id)
        
        # Should have unique correlation IDs for each source_guid
        assert len(all_unique_ids) == num_different_guids

    def test_concurrent_registry_clearing(self):
        """Test that registry clearing is thread-safe and deterministic generation persists."""
        source_guid = "clear-test-guid"
        loop_base_name = "clear_test_loop"
        
        # First, populate the registry
        original_id = ProcessorUtils.get_or_create_loop_correlation_id(source_guid, loop_base_name, self.get_test_session_id())
        assert original_id is not None
        
        # Verify it's consistent
        same_id = ProcessorUtils.get_or_create_loop_correlation_id(source_guid, loop_base_name, self.get_test_session_id())
        assert same_id == original_id
        
        clear_completed = threading.Event()
        
        def clear_worker():
            """Worker that clears the registry."""
            ProcessorUtils.clear_loop_correlation_registry()
            clear_completed.set()
        
        def access_worker():
            """Worker that tries to access the registry during clearing."""
            # Wait a bit to let clear start
            time.sleep(0.01)
            return ProcessorUtils.get_or_create_loop_correlation_id(source_guid, loop_base_name, self.get_test_session_id())
        
        # Start clear thread
        clear_thread = threading.Thread(target=clear_worker)
        clear_thread.start()
        
        # Start access thread
        access_thread = threading.Thread(target=access_worker)
        access_thread.start()
        
        # Wait for both to complete
        clear_thread.join()
        access_thread.join()
        
        # After clearing, should get the SAME ID (deterministic behavior)
        new_id = ProcessorUtils.get_or_create_loop_correlation_id(source_guid, loop_base_name, self.get_test_session_id())
        assert new_id == original_id, f"Deterministic generation should produce same ID after clearing: {original_id} vs {new_id}"

    def test_stress_test_many_concurrent_operations(self):
        """Stress test with many concurrent operations of different types."""
        num_workers = 20
        operations_per_worker = 50
        
        def worker(worker_id: int):
            """Worker that performs various operations."""
            for i in range(operations_per_worker):
                # Mix of different operations
                if i % 3 == 0:
                    # Source GUID based
                    ProcessorUtils.get_or_create_loop_correlation_id(
                        f"guid-{worker_id}-{i}", f"loop-{worker_id % 5}", self.get_test_session_id()
                    )
                elif i % 3 == 1:
                    # Position based
                    ProcessorUtils.get_or_create_position_based_loop_correlation_id(
                        i, f"pos-loop-{worker_id % 3}", self.get_test_session_id(), f"file-{worker_id % 2}"
                    )
                else:
                    # Same source GUID to test consistency
                    ProcessorUtils.get_or_create_loop_correlation_id(
                        "shared-guid", "shared-loop", self.get_test_session_id()
                    )
        
        # Start all workers
        threads = []
        for worker_id in range(num_workers):
            thread = threading.Thread(target=worker, args=(worker_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for all to complete
        for thread in threads:
            thread.join()
        
        # Verify the shared correlation ID is consistent
        shared_id_1 = ProcessorUtils.get_or_create_loop_correlation_id("shared-guid", "shared-loop", self.get_test_session_id())
        shared_id_2 = ProcessorUtils.get_or_create_loop_correlation_id("shared-guid", "shared-loop", self.get_test_session_id())
        assert shared_id_1 == shared_id_2

    def test_add_loop_correlation_id_thread_safety(self):
        """Test that add_loop_correlation_id is thread-safe."""
        agent_config = {
            'is_loop_agent': True,
            'loop_base_name': 'concurrent_loop',
            'workflow_session_id': self.get_test_session_id()
        }
        
        results: List[str] = []
        results_lock = threading.Lock()
        
        def worker(worker_id: int):
            """Worker that adds loop correlation IDs."""
            obj = {
                'source_guid': 'test-guid',
                'content': f'worker-{worker_id}'
            }
            
            updated_obj = ProcessorUtils.add_loop_correlation_id(obj, agent_config, record_index=0)
            
            with results_lock:
                if 'loop_correlation_id' in updated_obj:
                    results.append(updated_obj['loop_correlation_id'])
        
        # Start multiple workers
        num_workers = 25
        threads = []
        for worker_id in range(num_workers):
            thread = threading.Thread(target=worker, args=(worker_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # All results should have the same loop correlation ID
        assert len(results) == num_workers
        unique_ids = set(results)
        assert len(unique_ids) == 1, f"Expected 1 unique ID, got {len(unique_ids)}: {unique_ids}"

    def test_thread_pool_executor_consistency(self):
        """Test consistency using ThreadPoolExecutor for more realistic concurrency."""
        source_guid = "executor-test-guid"
        loop_base_name = "executor_loop"
        
        def get_correlation_id():
            """Function to be executed in thread pool."""
            return ProcessorUtils.get_or_create_loop_correlation_id(source_guid, loop_base_name, self.get_test_session_id())
        
        # Use ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit many tasks
            futures = [executor.submit(get_correlation_id) for _ in range(100)]
            
            # Collect results
            correlation_ids = []
            for future in as_completed(futures):
                correlation_ids.append(future.result())
        
        # All should be the same
        unique_ids = set(correlation_ids)
        assert len(unique_ids) == 1, f"Expected 1 unique ID, got {len(unique_ids)}: {unique_ids}"
        assert len(correlation_ids) == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])