"""
Integration tests for ProcessorUtils thread safety in realistic scenarios.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from agent_actions.utils.correlation import VersionIdGenerator


class TestProcessorUtilsIntegration:
    """Integration tests for ProcessorUtils in realistic parallel processing scenarios."""

    @classmethod
    def get_test_session_id(cls) -> str:
        """Get a consistent session ID for testing."""
        return "test_session_integration"

    def setup_method(self):
        """Clear the registry before each test."""
        VersionIdGenerator.clear_version_correlation_registry()

    def teardown_method(self):
        """Clear the registry after each test."""
        VersionIdGenerator.clear_version_correlation_registry()

    def test_parallel_loop_agents_simulation(self):
        """Simulate parallel loop agents processing the same data."""
        source_records = [{"source_guid": f"record-{i}", "content": f"data-{i}"} for i in range(10)]
        loop_agents = ["generate_distractors_1", "generate_distractors_2", "generate_distractors_3"]
        version_base_name = "generate_distractors"
        results: dict[str, list[str]] = {}
        results_lock = threading.Lock()

        def simulate_loop_agent(agent_name: str, records: list[dict]):
            """Simulate a loop agent processing records."""
            for record in records:
                source_guid = record["source_guid"]
                correlation_id = VersionIdGenerator.get_or_create_version_correlation_id(
                    source_guid, version_base_name, self.get_test_session_id()
                )
                time.sleep(0.001)
                with results_lock:
                    if source_guid not in results:
                        results[source_guid] = []
                    results[source_guid].append(correlation_id)

        threads = []
        for agent_name in loop_agents:
            thread = threading.Thread(target=simulate_loop_agent, args=(agent_name, source_records))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        assert len(results) == len(source_records)
        for source_guid, correlation_ids in results.items():
            assert len(correlation_ids) == len(loop_agents)
            unique_ids = set(correlation_ids)
            assert len(unique_ids) == 1, f"Source {source_guid} has inconsistent IDs: {unique_ids}"
        all_correlation_ids = set()
        for correlation_ids in results.values():
            correlation_id = correlation_ids[0]
            assert correlation_id not in all_correlation_ids, (
                f"Duplicate correlation ID: {correlation_id}"
            )
            all_correlation_ids.add(correlation_id)

    def test_position_based_batch_processing_simulation(self):
        """Simulate position-based correlation ID generation in batch processing."""
        batch_size = 5
        num_parallel_processors = 4
        version_base_name = "batch_processor"
        file_context = "batch_file.json"
        results: dict[int, list[str]] = {}
        results_lock = threading.Lock()

        def simulate_batch_processor(processor_id: int):
            """Simulate a batch processor working on specific positions."""
            for position in range(batch_size):
                correlation_id = (
                    VersionIdGenerator.get_or_create_position_based_version_correlation_id(
                        position, version_base_name, self.get_test_session_id(), file_context
                    )
                )
                time.sleep(0.002)
                with results_lock:
                    if position not in results:
                        results[position] = []
                    results[position].append(correlation_id)

        threads = []
        for processor_id in range(num_parallel_processors):
            thread = threading.Thread(target=simulate_batch_processor, args=(processor_id,))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        assert len(results) == batch_size
        for position, correlation_ids in results.items():
            assert len(correlation_ids) == num_parallel_processors
            unique_ids = set(correlation_ids)
            assert len(unique_ids) == 1, f"Position {position} has inconsistent IDs: {unique_ids}"
        all_position_ids = set()
        for correlation_ids in results.values():
            correlation_id = correlation_ids[0]
            assert correlation_id not in all_position_ids, (
                f"Duplicate correlation ID: {correlation_id}"
            )
            all_position_ids.add(correlation_id)

    def test_mixed_correlation_strategies_simulation(self):
        """Simulate mixed use of source_guid and position-based correlation strategies."""
        source_guids = [f"guid-{i}" for i in range(5)]
        positions = list(range(5))
        version_base_name = "mixed_loop"
        guid_results: dict[str, list[str]] = {}
        position_results: dict[int, list[str]] = {}
        results_lock = threading.Lock()

        def worker_source_guid(source_guid: str):
            """Worker using source_guid strategy."""
            for _ in range(3):
                correlation_id = VersionIdGenerator.get_or_create_version_correlation_id(
                    source_guid, version_base_name, self.get_test_session_id()
                )
                with results_lock:
                    if source_guid not in guid_results:
                        guid_results[source_guid] = []
                    guid_results[source_guid].append(correlation_id)

        def worker_position(position: int):
            """Worker using position strategy."""
            for _ in range(3):
                correlation_id = (
                    VersionIdGenerator.get_or_create_position_based_version_correlation_id(
                        position, version_base_name, self.get_test_session_id()
                    )
                )
                with results_lock:
                    if position not in position_results:
                        position_results[position] = []
                    position_results[position].append(correlation_id)

        threads = []
        for source_guid in source_guids:
            thread = threading.Thread(target=worker_source_guid, args=(source_guid,))
            threads.append(thread)
            thread.start()
        for position in positions:
            thread = threading.Thread(target=worker_position, args=(position,))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        for source_guid, correlation_ids in guid_results.items():
            unique_ids = set(correlation_ids)
            assert len(unique_ids) == 1, (
                f"Source GUID {source_guid} has inconsistent IDs: {unique_ids}"
            )
        for position, correlation_ids in position_results.items():
            unique_ids = set(correlation_ids)
            assert len(unique_ids) == 1, f"Position {position} has inconsistent IDs: {unique_ids}"
        guid_ids = {correlation_ids[0] for correlation_ids in guid_results.values()}
        position_ids = {correlation_ids[0] for correlation_ids in position_results.values()}
        overlap = guid_ids.intersection(position_ids)
        assert len(overlap) == 0, f"Unexpected overlap between strategies: {overlap}"

    def test_realistic_workflow_simulation(self):
        """Simulate a realistic workflow with loop agents and correlation."""
        input_data = [
            {"source_guid": f"input-{i}", "content": f"original-data-{i}"} for i in range(8)
        ]
        agent_config = {
            "is_versioned_agent": True,
            "version_base_name": "workflow_loop",
            "workflow_session_id": self.get_test_session_id(),
        }
        all_outputs: list[dict[str, Any]] = []
        outputs_lock = threading.Lock()

        def simulate_loop_agent_processing(agent_id: int, data_subset: list[dict]):
            """Simulate a loop agent processing a subset of data."""
            for record_index, item in enumerate(data_subset):
                processed_item = VersionIdGenerator.add_version_correlation_id(
                    item.copy(), agent_config, record_index=record_index
                )
                time.sleep(0.001)
                processed_item["processed_by"] = f"agent-{agent_id}"
                processed_item["processing_time"] = time.time()
                with outputs_lock:
                    all_outputs.append(processed_item)

        num_agents = 3
        chunk_size = len(input_data) // num_agents
        with ThreadPoolExecutor(max_workers=num_agents) as executor:
            futures = []
            for agent_id in range(num_agents):
                start_idx = agent_id * chunk_size
                end_idx = start_idx + chunk_size if agent_id < num_agents - 1 else len(input_data)
                data_subset = input_data[start_idx:end_idx]
                future = executor.submit(simulate_loop_agent_processing, agent_id, data_subset)
                futures.append(future)
            for future in futures:
                future.result()
        assert len(all_outputs) == len(input_data)
        outputs_by_guid: dict[str, list[dict]] = {}
        for output in all_outputs:
            source_guid = output["source_guid"]
            if source_guid not in outputs_by_guid:
                outputs_by_guid[source_guid] = []
            outputs_by_guid[source_guid].append(output)
        for source_guid, outputs in outputs_by_guid.items():
            assert len(outputs) == 1, f"Source {source_guid} has {len(outputs)} outputs, expected 1"
            output = outputs[0]
            assert "version_correlation_id" in output, f"Missing version_correlation_id in {output}"
            assert output["version_correlation_id"] is not None
        correlation_ids = {
            outputs[0]["version_correlation_id"] for outputs in outputs_by_guid.values()
        }
        expected_positions = set()
        chunk_size = len(input_data) // 3
        for agent_id in range(3):
            start_idx = agent_id * chunk_size
            end_idx = start_idx + chunk_size if agent_id < 3 - 1 else len(input_data)
            chunk_len = end_idx - start_idx
            expected_positions.update(range(chunk_len))
        assert len(correlation_ids) == len(expected_positions), (
            f"Expected {len(expected_positions)} unique correlation IDs, got {len(correlation_ids)}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
