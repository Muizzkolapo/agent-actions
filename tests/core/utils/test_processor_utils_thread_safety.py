"""
Tests for ProcessorUtils thread safety, specifically the loop correlation ID race condition fix.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from agent_actions.utils.correlation import VersionIdGenerator


class TestProcessorUtilsThreadSafety:
    """Test suite for ProcessorUtils thread safety."""

    @classmethod
    def get_test_session_id(cls) -> str:
        """Get a consistent session ID for testing."""
        return "test_session_12345"

    def setup_method(self):
        """Clear the registry before each test."""
        VersionIdGenerator.clear_version_correlation_registry()

    def teardown_method(self):
        """Clear the registry after each test."""
        VersionIdGenerator.clear_version_correlation_registry()

    def test_concurrent_version_correlation_id_generation_consistency(self):
        """Test that concurrent access generates consistent correlation IDs."""
        source_guid = "test-guid-123"
        version_base_name = "generate_distractors"
        num_threads = 50
        num_calls_per_thread = 10
        correlation_ids: list[str] = []
        correlation_ids_lock = threading.Lock()

        def worker():
            """Worker function that generates correlation IDs."""
            local_ids = []
            for _ in range(num_calls_per_thread):
                correlation_id = VersionIdGenerator.get_or_create_version_correlation_id(
                    source_guid, version_base_name, self.get_test_session_id()
                )
                local_ids.append(correlation_id)
                time.sleep(0.001)
            with correlation_ids_lock:
                correlation_ids.extend(local_ids)

        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        unique_ids = set(correlation_ids)
        assert len(unique_ids) == 1, f"Expected 1 unique ID, got {len(unique_ids)}: {unique_ids}"
        assert len(correlation_ids) == num_threads * num_calls_per_thread

    def test_concurrent_position_based_correlation_id_consistency(self):
        """Test that position-based correlation IDs are consistent across threads."""
        record_index = 42
        version_base_name = "process_items"
        file_context = "test_file.json"
        num_threads = 30
        correlation_ids: list[str] = []
        correlation_ids_lock = threading.Lock()

        def worker():
            """Worker function that generates position-based correlation IDs."""
            correlation_id = VersionIdGenerator.get_or_create_position_based_version_correlation_id(
                record_index, version_base_name, self.get_test_session_id(), file_context
            )
            with correlation_ids_lock:
                correlation_ids.append(correlation_id)

        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        unique_ids = set(correlation_ids)
        assert len(unique_ids) == 1, f"Expected 1 unique ID, got {len(unique_ids)}: {unique_ids}"

    def test_concurrent_different_keys_generate_different_ids(self):
        """Test that different keys generate different correlation IDs even under concurrency."""
        version_base_name = "test_loop"
        num_different_guids = 10
        num_threads_per_guid = 5
        all_results = {}
        results_lock = threading.Lock()

        def worker(source_guid: str):
            """Worker function for a specific source_guid."""
            correlation_id = VersionIdGenerator.get_or_create_version_correlation_id(
                source_guid, version_base_name, self.get_test_session_id()
            )
            with results_lock:
                if source_guid not in all_results:
                    all_results[source_guid] = []
                all_results[source_guid].append(correlation_id)

        threads = []
        for i in range(num_different_guids):
            source_guid = f"guid-{i}"
            for _ in range(num_threads_per_guid):
                thread = threading.Thread(target=worker, args=(source_guid,))
                threads.append(thread)
                thread.start()
        for thread in threads:
            thread.join()
        assert len(all_results) == num_different_guids
        all_unique_ids = set()
        for source_guid, ids in all_results.items():
            unique_ids_for_guid = set(ids)
            assert len(unique_ids_for_guid) == 1, (
                f"Source {source_guid} has inconsistent IDs: {unique_ids_for_guid}"
            )
            correlation_id = list(unique_ids_for_guid)[0]
            assert correlation_id not in all_unique_ids, (
                f"Duplicate correlation ID {correlation_id}"
            )
            all_unique_ids.add(correlation_id)
        assert len(all_unique_ids) == num_different_guids

    def test_concurrent_registry_clearing(self):
        """Test that registry clearing is thread-safe and deterministic generation persists."""
        source_guid = "clear-test-guid"
        version_base_name = "clear_test_loop"
        original_id = VersionIdGenerator.get_or_create_version_correlation_id(
            source_guid, version_base_name, self.get_test_session_id()
        )
        assert original_id is not None
        same_id = VersionIdGenerator.get_or_create_version_correlation_id(
            source_guid, version_base_name, self.get_test_session_id()
        )
        assert same_id == original_id
        clear_completed = threading.Event()

        def clear_worker():
            """Worker that clears the registry."""
            VersionIdGenerator.clear_version_correlation_registry()
            clear_completed.set()

        def access_worker():
            """Worker that tries to access the registry during clearing."""
            time.sleep(0.01)
            return VersionIdGenerator.get_or_create_version_correlation_id(
                source_guid, version_base_name, self.get_test_session_id()
            )

        clear_thread = threading.Thread(target=clear_worker)
        clear_thread.start()
        access_thread = threading.Thread(target=access_worker)
        access_thread.start()
        clear_thread.join()
        access_thread.join()
        new_id = VersionIdGenerator.get_or_create_version_correlation_id(
            source_guid, version_base_name, self.get_test_session_id()
        )
        assert new_id == original_id, (
            f"Deterministic generation should produce same ID after clearing: {original_id} vs {new_id}"
        )

    def test_stress_test_many_concurrent_operations(self):
        """Stress test with many concurrent operations of different types."""
        num_workers = 20
        operations_per_worker = 50

        def worker(worker_id: int):
            """Worker that performs various operations."""
            for i in range(operations_per_worker):
                if i % 3 == 0:
                    VersionIdGenerator.get_or_create_version_correlation_id(
                        f"guid-{worker_id}-{i}", f"loop-{worker_id % 5}", self.get_test_session_id()
                    )
                elif i % 3 == 1:
                    VersionIdGenerator.get_or_create_position_based_version_correlation_id(
                        i,
                        f"pos-loop-{worker_id % 3}",
                        self.get_test_session_id(),
                        f"file-{worker_id % 2}",
                    )
                else:
                    VersionIdGenerator.get_or_create_version_correlation_id(
                        "shared-guid", "shared-loop", self.get_test_session_id()
                    )

        threads = []
        for worker_id in range(num_workers):
            thread = threading.Thread(target=worker, args=(worker_id,))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        shared_id_1 = VersionIdGenerator.get_or_create_version_correlation_id(
            "shared-guid", "shared-loop", self.get_test_session_id()
        )
        shared_id_2 = VersionIdGenerator.get_or_create_version_correlation_id(
            "shared-guid", "shared-loop", self.get_test_session_id()
        )
        assert shared_id_1 == shared_id_2

    def test_add_version_correlation_id_thread_safety(self):
        """Test that add_version_correlation_id is thread-safe."""
        agent_config = {
            "is_versioned_agent": True,
            "version_base_name": "concurrent_loop",
            "workflow_session_id": self.get_test_session_id(),
        }
        results: list[str] = []
        results_lock = threading.Lock()

        def worker(worker_id: int):
            """Worker that adds loop correlation IDs."""
            obj = {"source_guid": "test-guid", "content": f"worker-{worker_id}"}
            updated_obj = VersionIdGenerator.add_version_correlation_id(
                obj, agent_config, record_index=0
            )
            with results_lock:
                if "version_correlation_id" in updated_obj:
                    results.append(updated_obj["version_correlation_id"])

        num_workers = 25
        threads = []
        for worker_id in range(num_workers):
            thread = threading.Thread(target=worker, args=(worker_id,))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        assert len(results) == num_workers
        unique_ids = set(results)
        assert len(unique_ids) == 1, f"Expected 1 unique ID, got {len(unique_ids)}: {unique_ids}"

    def test_thread_pool_executor_consistency(self):
        """Test consistency using ThreadPoolExecutor for more realistic concurrency."""
        source_guid = "executor-test-guid"
        version_base_name = "executor_loop"

        def get_correlation_id():
            """Function to be executed in thread pool."""
            return VersionIdGenerator.get_or_create_version_correlation_id(
                source_guid, version_base_name, self.get_test_session_id()
            )

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(get_correlation_id) for _ in range(100)]
            correlation_ids = []
            for future in as_completed(futures):
                correlation_ids.append(future.result())
        unique_ids = set(correlation_ids)
        assert len(unique_ids) == 1, f"Expected 1 unique ID, got {len(unique_ids)}: {unique_ids}"
        assert len(correlation_ids) == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
