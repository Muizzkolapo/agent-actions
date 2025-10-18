"""
Tests for multi-batch correlation ID consistency - the core issue this PR fixes.

This test file validates that the deterministic correlation ID fix resolves
the issue where different batch sessions generate different correlation IDs
for the same logical records.
"""

import threading
import time
import pytest
from typing import Dict, List, Set

from agent_actions.core.utils.processor_utils import ProcessorUtils


class TestMultiBatchCorrelationConsistency:
    """Test suite for multi-batch correlation ID consistency."""

    @classmethod
    def get_shared_session_id(cls) -> str:
        """Simulate a shared workflow session ID across all batches."""
        return "workflow_1697385600_abc12345"

    def setup_method(self):
        """Clear the registry before each test."""
        ProcessorUtils.clear_loop_correlation_registry()

    def teardown_method(self):
        """Clear the registry after each test."""
        ProcessorUtils.clear_loop_correlation_registry()

    def test_same_session_produces_identical_correlation_ids(self):
        """Test that same session + same input = identical correlation IDs."""
        session_id = self.get_shared_session_id()
        source_guid = "record-123"
        loop_base_name = "generate_distractors"

        # Generate correlation ID
        id1 = ProcessorUtils.get_or_create_loop_correlation_id(
            source_guid, loop_base_name, session_id
        )

        # Clear registry (simulates session restart)
        ProcessorUtils.clear_loop_correlation_registry()

        # Generate again - should be identical (deterministic)
        id2 = ProcessorUtils.get_or_create_loop_correlation_id(
            source_guid, loop_base_name, session_id
        )

        assert id1 == id2, f"Expected identical IDs, got {id1} and {id2}"

    def test_different_sessions_produce_different_correlation_ids(self):
        """Test that different sessions produce different correlation IDs."""
        source_guid = "record-123"
        loop_base_name = "generate_distractors"

        # Session 1
        id1 = ProcessorUtils.get_or_create_loop_correlation_id(
            source_guid, loop_base_name, "session_1"
        )

        # Session 2
        id2 = ProcessorUtils.get_or_create_loop_correlation_id(
            source_guid, loop_base_name, "session_2"
        )

        assert id1 != id2, f"Expected different IDs for different sessions, got {id1} and {id2}"

    def test_multi_batch_session_simulation(self):
        """
        Simulate the original problem: 3 batches completing at different times.
        
        Scenario:
        1. Batch 1 & 2 complete together → sessions end → registry cleared
        2. Batch 3 completes later → should still get same correlation IDs
        """
        shared_session_id = self.get_shared_session_id()
        source_records = [
            {"source_guid": "record-1", "content": "data-1"},
            {"source_guid": "record-2", "content": "data-2"},
            {"source_guid": "record-3", "content": "data-3"}
        ]
        loop_base_name = "generate_distractors"

        # === Batch 1 & 2 Complete (simultaneous) ===
        batch_1_2_results = {}
        
        def simulate_batch_1_2():
            """Simulate batches 1 & 2 completing simultaneously."""
            for record in source_records:
                source_guid = record["source_guid"]
                correlation_id = ProcessorUtils.get_or_create_loop_correlation_id(
                    source_guid, loop_base_name, shared_session_id
                )
                batch_1_2_results[source_guid] = correlation_id

        # Run batch 1 & 2
        simulate_batch_1_2()
        
        # Store results for comparison
        original_results = batch_1_2_results.copy()
        
        # === Simulate Session End (registry clear) ===
        ProcessorUtils.clear_loop_correlation_registry()
        
        # === Batch 3 Completes Later ===
        batch_3_results = {}
        
        def simulate_batch_3():
            """Simulate batch 3 completing after session restart."""
            for record in source_records:
                source_guid = record["source_guid"]
                correlation_id = ProcessorUtils.get_or_create_loop_correlation_id(
                    source_guid, loop_base_name, shared_session_id
                )
                batch_3_results[source_guid] = correlation_id

        # Run batch 3
        simulate_batch_3()
        
        # === Validate Consistency ===
        for source_guid in source_records[0].keys():
            if source_guid == "content":  # Skip content field
                continue
                
            source_guid_key = source_guid
            for record in source_records:
                if record.get("source_guid") == source_guid_key:
                    actual_source_guid = record["source_guid"]
                    break
            else:
                actual_source_guid = source_guid_key
                
        # Check each source record
        for record in source_records:
            source_guid = record["source_guid"]
            batch_1_2_id = original_results[source_guid]
            batch_3_id = batch_3_results[source_guid]
            
            assert batch_1_2_id == batch_3_id, (
                f"Correlation ID mismatch for {source_guid}: "
                f"Batch 1&2: {batch_1_2_id}, Batch 3: {batch_3_id}"
            )

        print(f"✅ All batches produced consistent correlation IDs:")
        for record in source_records:
            source_guid = record["source_guid"]
            correlation_id = original_results[source_guid]
            print(f"  {source_guid}: {correlation_id}")

    def test_position_based_multi_batch_consistency(self):
        """Test position-based correlation IDs across multiple batch sessions."""
        shared_session_id = self.get_shared_session_id()
        positions = [0, 1, 2, 3, 4]
        loop_base_name = "batch_processor"
        file_context = "batch_file.json"

        # === Batch 1 Results ===
        batch_1_results = {}
        for position in positions:
            correlation_id = ProcessorUtils.get_or_create_position_based_loop_correlation_id(
                position, loop_base_name, shared_session_id, file_context
            )
            batch_1_results[position] = correlation_id

        # === Simulate Session Restart ===
        ProcessorUtils.clear_loop_correlation_registry()

        # === Batch 2 Results ===
        batch_2_results = {}
        for position in positions:
            correlation_id = ProcessorUtils.get_or_create_position_based_loop_correlation_id(
                position, loop_base_name, shared_session_id, file_context
            )
            batch_2_results[position] = correlation_id

        # === Validate Consistency ===
        for position in positions:
            batch_1_id = batch_1_results[position]
            batch_2_id = batch_2_results[position]
            
            assert batch_1_id == batch_2_id, (
                f"Position-based correlation ID mismatch for position {position}: "
                f"Batch 1: {batch_1_id}, Batch 2: {batch_2_id}"
            )

    def test_concurrent_multi_batch_scenario(self):
        """Test concurrent batches with shared session ID."""
        shared_session_id = self.get_shared_session_id()
        source_records = [f"record-{i}" for i in range(10)]
        loop_base_name = "concurrent_loop"
        
        # Store results from all concurrent batches
        all_results: Dict[int, Dict[str, str]] = {}
        results_lock = threading.Lock()

        def simulate_batch(batch_id: int):
            """Simulate a batch processing records."""
            batch_results = {}
            for source_guid in source_records:
                correlation_id = ProcessorUtils.get_or_create_loop_correlation_id(
                    source_guid, loop_base_name, shared_session_id
                )
                batch_results[source_guid] = correlation_id
                # Add small delay to increase concurrency
                time.sleep(0.001)
            
            with results_lock:
                all_results[batch_id] = batch_results

        # Start 5 concurrent batches
        num_batches = 5
        threads = []
        for batch_id in range(num_batches):
            thread = threading.Thread(target=simulate_batch, args=(batch_id,))
            threads.append(thread)
            thread.start()

        # Wait for all batches to complete
        for thread in threads:
            thread.join()

        # Validate that all batches produced identical correlation IDs
        reference_results = all_results[0]  # Use first batch as reference
        
        for batch_id in range(1, num_batches):
            batch_results = all_results[batch_id]
            
            for source_guid in source_records:
                reference_id = reference_results[source_guid]
                batch_id_result = batch_results[source_guid]
                
                assert reference_id == batch_id_result, (
                    f"Correlation ID mismatch between batch 0 and batch {batch_id} "
                    f"for {source_guid}: {reference_id} vs {batch_id_result}"
                )

        print(f"✅ All {num_batches} concurrent batches produced identical correlation IDs")

    def test_workflow_session_id_isolation(self):
        """Test that different workflow session IDs are properly isolated."""
        source_guid = "shared-record"
        loop_base_name = "shared-loop"
        
        # Workflow 1
        workflow_1_session = "workflow_1_session"
        id1 = ProcessorUtils.get_or_create_loop_correlation_id(
            source_guid, loop_base_name, workflow_1_session
        )
        
        # Workflow 2
        workflow_2_session = "workflow_2_session"
        id2 = ProcessorUtils.get_or_create_loop_correlation_id(
            source_guid, loop_base_name, workflow_2_session
        )
        
        # Workflow 1 again (should be same as first)
        id3 = ProcessorUtils.get_or_create_loop_correlation_id(
            source_guid, loop_base_name, workflow_1_session
        )
        
        # Assertions
        assert id1 != id2, f"Different workflows should have different IDs: {id1} vs {id2}"
        assert id1 == id3, f"Same workflow should have same ID: {id1} vs {id3}"

    def test_add_loop_correlation_id_with_workflow_session(self):
        """Test the add_loop_correlation_id method with workflow session ID."""
        shared_session_id = self.get_shared_session_id()
        
        # Create agent config with workflow session ID
        agent_config = {
            'is_loop_agent': True,
            'loop_base_name': 'test_loop',
            'workflow_session_id': shared_session_id
        }
        
        # Test record
        record = {
            'source_guid': 'test-record-123',
            'content': 'test data'
        }
        
        # Add correlation ID
        result1 = ProcessorUtils.add_loop_correlation_id(record, agent_config)
        
        # Clear registry and add again - should be deterministic
        ProcessorUtils.clear_loop_correlation_registry()
        result2 = ProcessorUtils.add_loop_correlation_id(record, agent_config)
        
        # Validate
        assert 'loop_correlation_id' in result1
        assert 'loop_correlation_id' in result2
        assert result1['loop_correlation_id'] == result2['loop_correlation_id']
        
        print(f"✅ add_loop_correlation_id produces deterministic results: {result1['loop_correlation_id']}")

    def test_missing_session_id_raises_error(self):
        """Test that missing workflow_session_id raises a clear error (fail-fast)."""
        # Agent config without workflow_session_id
        agent_config = {
            'is_loop_agent': True,
            'loop_base_name': 'missing_session_loop'
        }
        
        record = {
            'source_guid': 'test-record',
            'content': 'test data'
        }
        
        # This should raise a ValueError with clear error message
        with pytest.raises(ValueError) as exc_info:
            ProcessorUtils.add_loop_correlation_id(record, agent_config)
        
        error_message = str(exc_info.value)
        assert "Missing workflow_session_id" in error_message
        assert "deterministic correlation IDs" in error_message
        assert "AgentWorkflow properly injects" in error_message
        
        print(f"✅ Fail-fast behavior works: {error_message}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])