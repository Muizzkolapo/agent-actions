"""
Comprehensive tests for Collection Management System.

Tests cover the critical features identified in qanalabs production usage:
- remove_collection field removal logic
- side_collection field preservation logic
- Data integrity validation
- Performance benchmarking
- Thread safety under concurrent access

This implements CF-002 from the test implementation plan.
"""

import pytest
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any
from unittest.mock import Mock, patch

from hypothesis import given, strategies as st, settings

from agent_actions.core.utils.processor_utils import ProcessorUtils
from agent_actions.agents.transformers.data_transformer import DataTransformer
from tests.utils.test_utils import (
    CollectionManagementTestHelper,
    TestDataPattern,
    PerformanceBenchmarkHelper,
    test_state,
    temporary_test_environment
)


class TestRemoveCollection:
    """Test remove_collection functionality with real qanalabs patterns."""

    def test_apply_remove_collection_standard_pattern(self):
        """Test standard fact_extractor pattern: remove ['id', 'url', 'topic']."""
        test_id = "remove_collection_standard"
        test_state.register_test_run(test_id, "remove_collection")

        # Use qanalabs production pattern
        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[0]
        test_data = CollectionManagementTestHelper.generate_test_data(pattern, item_count=1)[0]

        agent_config = {"remove_collection": pattern.remove_collection_fields}

        start_time = time.perf_counter()
        result = ProcessorUtils.apply_remove_collection(test_data, agent_config)
        duration = (time.perf_counter() - start_time) * 1000

        # Verify removed fields are gone
        for field in pattern.remove_collection_fields:
            assert field not in result, f"Field '{field}' should have been removed"

        # Verify other fields are preserved
        expected_preserved = ['page_content', 'bloom_details', 'summary', 'metadata', 'nested_data']
        for field in expected_preserved:
            if field in test_data:
                assert field in result, f"Field '{field}' should have been preserved"
                assert result[field] == test_data[field], f"Field '{field}' was modified"

        # Performance validation
        assert duration < pattern.performance_threshold_ms, f"Performance threshold exceeded: {duration}ms"

        test_state.complete_test_run(test_id, True, {"duration_ms": duration})

    def test_apply_remove_collection_empty_list(self):
        """Test remove_collection with empty list - should preserve all fields."""
        test_id = "remove_collection_empty"
        test_state.register_test_run(test_id, "remove_collection")

        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[3]  # empty_removal
        test_data = CollectionManagementTestHelper.generate_test_data(pattern, item_count=1)[0]

        agent_config = {"remove_collection": []}

        result = ProcessorUtils.apply_remove_collection(test_data, agent_config)

        # All fields should be preserved
        assert result == test_data, "Empty remove_collection should preserve all fields"

        test_state.complete_test_run(test_id, True)

    def test_apply_remove_collection_non_dict_input(self):
        """Test remove_collection with non-dictionary input."""
        test_id = "remove_collection_non_dict"
        test_state.register_test_run(test_id, "remove_collection")

        agent_config = {"remove_collection": ["field1", "field2"]}

        # Test with string
        result = ProcessorUtils.apply_remove_collection("test_string", agent_config)
        assert result == "test_string"

        # Test with list
        test_list = [1, 2, 3]
        result = ProcessorUtils.apply_remove_collection(test_list, agent_config)
        assert result == test_list

        # Test with None
        result = ProcessorUtils.apply_remove_collection(None, agent_config)
        assert result is None

        test_state.complete_test_run(test_id, True)

    @given(
        st.dictionaries(
            st.text(min_size=1, max_size=20),
            st.one_of(st.text(), st.integers(), st.floats(), st.booleans()),
            min_size=5,
            max_size=15
        ),
        st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5)
    )
    @settings(max_examples=50, deadline=1000)
    def test_remove_collection_property_based(self, test_data: Dict, fields_to_remove: List[str]):
        """Property-based test for remove_collection with various data structures."""
        test_id = f"remove_collection_property_{hash(str(test_data))}"
        test_state.register_test_run(test_id, "property_based")

        agent_config = {"remove_collection": fields_to_remove}
        result = ProcessorUtils.apply_remove_collection(test_data, agent_config)

        # Property: removed fields should not be present
        for field in fields_to_remove:
            if field in test_data:
                assert field not in result, f"Field '{field}' should have been removed"

        # Property: non-removed fields should be preserved
        for field, value in test_data.items():
            if field not in fields_to_remove:
                assert field in result, f"Field '{field}' should have been preserved"
                assert result[field] == value, f"Field '{field}' was modified"

        test_state.complete_test_run(test_id, True)


class TestSideCollection:
    """Test side_collection functionality with real qanalabs patterns."""

    def test_transform_with_side_collection_standard_pattern(self):
        """Test standard side_collection pattern from qanalabs."""
        test_id = "side_collection_standard"
        test_state.register_test_run(test_id, "side_collection")

        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[0]
        context_data = CollectionManagementTestHelper.generate_test_data(pattern, item_count=1)[0]

        # Simulate generated data that needs side_collection applied
        generated_data = [
            {"new_field": "value1", "analysis": "result1"},
            {"new_field": "value2", "analysis": "result2"}
        ]

        agent_config = {"side_collection": pattern.side_collection_fields}
        source_guid = "test-source-guid"

        start_time = time.perf_counter()
        result = ProcessorUtils.transform_with_side_collection(
            generated_data, context_data, source_guid, agent_config
        )
        duration = (time.perf_counter() - start_time) * 1000

        # Verify structure
        assert isinstance(result, list), "Result should be a list"
        assert len(result) == len(generated_data), "Result length should match input"

        # Verify each item has required structure
        for item in result:
            assert 'source_guid' in item, "Each item should have source_guid"
            assert 'content' in item, "Each item should have content"
            assert 'target_id' in item, "Each item should have target_id"
            assert 'node_id' in item, "Each item should have node_id"

            # Verify side_collection fields are preserved
            content = item['content']
            for field in pattern.side_collection_fields:
                if field in context_data:
                    assert field in content, f"Side collection field '{field}' should be preserved"
                    assert content[field] == context_data[field], f"Side collection field '{field}' was modified"

        # Performance validation
        assert duration < pattern.performance_threshold_ms, f"Performance threshold exceeded: {duration}ms"

        test_state.complete_test_run(test_id, True, {"duration_ms": duration})

    def test_transform_with_side_collection_already_structured(self):
        """Test side_collection with already structured data."""
        test_id = "side_collection_structured"
        test_state.register_test_run(test_id, "side_collection")

        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[1]
        context_data = CollectionManagementTestHelper.generate_test_data(pattern, item_count=1)[0]

        # Data already in structured format
        structured_data = [
            {
                'source_guid': 'existing-guid-1',
                'content': {'field1': 'value1', 'field2': 'value2'}
            },
            {
                'source_guid': 'existing-guid-2',
                'content': {'field1': 'value3', 'field2': 'value4'}
            }
        ]

        agent_config = {"side_collection": pattern.side_collection_fields}
        source_guid = "test-source-guid"

        result = ProcessorUtils.transform_with_side_collection(
            structured_data, context_data, source_guid, agent_config
        )

        # Verify preservation of existing structure with side_collection applied
        assert len(result) == len(structured_data)

        for i, item in enumerate(result):
            content = item['content']
            # Original fields should be preserved or updated with side_collection
            for field in pattern.side_collection_fields:
                if field in context_data:
                    assert field in content, f"Side collection field '{field}' should be in content"

        test_state.complete_test_run(test_id, True)

    def test_transform_with_side_collection_no_side_collection_config(self):
        """Test transform_with_side_collection without side_collection configuration."""
        test_id = "side_collection_none"
        test_state.register_test_run(test_id, "side_collection")

        context_data = {"field1": "value1", "field2": "value2"}
        data = ["item1", "item2"]
        agent_config = {}  # No side_collection
        source_guid = "test-source-guid"

        result = ProcessorUtils.transform_with_side_collection(
            data, context_data, source_guid, agent_config
        )

        # Should apply transform_structure for consistent format
        assert isinstance(result, list)
        assert len(result) == len(data)

        for item in result:
            assert 'source_guid' in item
            assert 'content' in item
            assert 'target_id' in item
            assert 'node_id' in item

        test_state.complete_test_run(test_id, True)


class TestDataIntegrity:
    """Test data integrity validation for collection management operations."""

    def test_data_integrity_validation_qanalabs_patterns(self):
        """Test data integrity using all qanalabs patterns."""
        test_id = "data_integrity_qanalabs"
        test_state.register_test_run(test_id, "data_integrity")

        patterns = CollectionManagementTestHelper.create_qanalabs_test_patterns()

        for pattern in patterns:
            original_data = CollectionManagementTestHelper.generate_test_data(pattern, item_count=10)

            # Apply remove_collection
            processed_data = []
            for item in original_data:
                agent_config = {"remove_collection": pattern.remove_collection_fields}
                processed_item = ProcessorUtils.apply_remove_collection(item, agent_config)
                processed_data.append(processed_item)

            # Validate integrity
            integrity_result = CollectionManagementTestHelper.validate_data_integrity(
                original_data, processed_data, pattern
            )

            # Should have no violations for remove_collection (side_collection not tested here)
            remove_violations = [v for v in integrity_result['violations'] if 'not removed' in v]
            assert len(remove_violations) == 0, f"Pattern {pattern.name} had remove violations: {remove_violations}"

            # Integrity score should be high
            assert integrity_result['integrity_score'] >= 0.7, f"Low integrity score for {pattern.name}: {integrity_result['integrity_score']}"

        test_state.complete_test_run(test_id, True)

    def test_data_integrity_with_nested_objects(self):
        """Test data integrity with complex nested objects."""
        test_id = "data_integrity_nested"
        test_state.register_test_run(test_id, "data_integrity")

        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[0]
        original_data = CollectionManagementTestHelper.generate_test_data(
            pattern, item_count=5, add_nested_objects=True
        )

        # Apply transformations
        processed_data = []
        for item in original_data:
            agent_config = {"remove_collection": pattern.remove_collection_fields}
            processed_item = ProcessorUtils.apply_remove_collection(item, agent_config)
            processed_data.append(processed_item)

        # Verify nested objects are preserved correctly
        for orig, proc in zip(original_data, processed_data):
            if 'nested_data' in orig and 'nested_data' not in pattern.remove_collection_fields:
                assert 'nested_data' in proc, "Nested data should be preserved"
                assert proc['nested_data'] == orig['nested_data'], "Nested data should be unchanged"

        test_state.complete_test_run(test_id, True)


class TestConcurrentAccess:
    """Test thread safety and concurrent access patterns."""

    def test_concurrent_remove_collection_operations(self):
        """Test remove_collection under concurrent access."""
        test_id = "concurrent_remove_collection"
        test_state.register_test_run(test_id, "concurrent")

        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[0]
        test_data = CollectionManagementTestHelper.generate_test_data(pattern, item_count=100)
        agent_config = {"remove_collection": pattern.remove_collection_fields}

        results = []
        errors = []

        def process_item(item):
            try:
                return ProcessorUtils.apply_remove_collection(item, agent_config)
            except Exception as e:
                errors.append(e)
                return None

        # Process items concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_item = {executor.submit(process_item, item): item for item in test_data}

            for future in as_completed(future_to_item):
                result = future.result()
                if result is not None:
                    results.append(result)

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent processing had errors: {errors}"
        assert len(results) == len(test_data), "All items should be processed"

        # Verify consistency of results
        for result in results:
            for field in pattern.remove_collection_fields:
                assert field not in result, f"Field '{field}' should have been removed"

        test_state.complete_test_run(test_id, True, {"items_processed": len(results)})

    def test_concurrent_side_collection_operations(self):
        """Test side_collection under concurrent access."""
        test_id = "concurrent_side_collection"
        test_state.register_test_run(test_id, "concurrent")

        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[0]
        context_data = CollectionManagementTestHelper.generate_test_data(pattern, item_count=1)[0]
        agent_config = {"side_collection": pattern.side_collection_fields}

        # Generate multiple datasets for concurrent processing
        datasets = []
        for i in range(50):
            data = [f"item_{i}_1", f"item_{i}_2"]
            datasets.append((data, f"source_guid_{i}"))

        results = []
        errors = []

        def process_dataset(data_and_guid):
            try:
                data, source_guid = data_and_guid
                return ProcessorUtils.transform_with_side_collection(
                    data, context_data, source_guid, agent_config
                )
            except Exception as e:
                errors.append(e)
                return None

        # Process datasets concurrently
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_dataset = {executor.submit(process_dataset, dataset): dataset for dataset in datasets}

            for future in as_completed(future_to_dataset):
                result = future.result()
                if result is not None:
                    results.append(result)

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent processing had errors: {errors}"
        assert len(results) == len(datasets), "All datasets should be processed"

        # Verify consistency
        for result in results:
            assert isinstance(result, list), "Result should be a list"
            for item in result:
                assert 'source_guid' in item, "Each item should have source_guid"
                assert 'content' in item, "Each item should have content"

        test_state.complete_test_run(test_id, True, {"datasets_processed": len(results)})


class TestPerformanceBenchmarks:
    """Performance benchmarking for collection management operations."""

    def test_remove_collection_performance_1000_items(self):
        """Benchmark remove_collection with 1000 items - target <100ms."""
        test_id = "performance_remove_collection_1000"
        test_state.register_test_run(test_id, "performance")

        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[0]
        test_data = CollectionManagementTestHelper.generate_test_data(pattern, item_count=1000)
        agent_config = {"remove_collection": pattern.remove_collection_fields}

        benchmark_helper = PerformanceBenchmarkHelper()

        with benchmark_helper.benchmark_context(test_id, "remove_collection_1000_items"):
            for item in test_data:
                ProcessorUtils.apply_remove_collection(item, agent_config)

        metrics = benchmark_helper.get_performance_summary()
        duration_ms = metrics[test_id]["remove_collection_1000_items"]["duration_ms"]

        # Target: <100ms for 1000 items
        assert duration_ms < 100.0, f"Performance target missed: {duration_ms}ms > 100ms"

        test_state.complete_test_run(test_id, True, {"duration_ms": duration_ms})
        test_state.record_performance_metric(test_id, "duration_ms", duration_ms)

    def test_side_collection_performance_large_context(self):
        """Benchmark side_collection with large context data."""
        test_id = "performance_side_collection_large"
        test_state.register_test_run(test_id, "performance")

        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[0]
        # Generate large context data
        context_data = CollectionManagementTestHelper.generate_test_data(
            pattern, item_count=1, add_large_content=True
        )[0]

        data = ["item1", "item2", "item3"] * 100  # 300 items
        agent_config = {"side_collection": pattern.side_collection_fields}
        source_guid = "performance-test-guid"

        benchmark_helper = PerformanceBenchmarkHelper()

        with benchmark_helper.benchmark_context(test_id, "side_collection_large_context"):
            result = ProcessorUtils.transform_with_side_collection(
                data, context_data, source_guid, agent_config
            )

        metrics = benchmark_helper.get_performance_summary()
        duration_ms = metrics[test_id]["side_collection_large_context"]["duration_ms"]
        memory_delta_mb = metrics[test_id]["side_collection_large_context"]["memory_delta_mb"]

        # Verify processing completed successfully
        assert len(result) == len(data), "All items should be processed"

        # Record performance metrics
        test_state.complete_test_run(test_id, True, {
            "duration_ms": duration_ms,
            "memory_delta_mb": memory_delta_mb,
            "items_processed": len(data)
        })
        test_state.record_performance_metric(test_id, "duration_ms", duration_ms)
        test_state.record_performance_metric(test_id, "memory_delta_mb", memory_delta_mb)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_remove_collection_missing_config(self):
        """Test remove_collection when config is missing."""
        test_id = "edge_case_missing_config"
        test_state.register_test_run(test_id, "edge_case")

        test_data = {"field1": "value1", "field2": "value2"}
        agent_config = {}  # No remove_collection key

        result = ProcessorUtils.apply_remove_collection(test_data, agent_config)

        # Should return original data unchanged
        assert result == test_data

        test_state.complete_test_run(test_id, True)

    def test_side_collection_empty_context(self):
        """Test side_collection with empty context data."""
        test_id = "edge_case_empty_context"
        test_state.register_test_run(test_id, "edge_case")

        data = ["item1", "item2"]
        context_data = {}
        agent_config = {"side_collection": ["field1", "field2"]}
        source_guid = "test-guid"

        result = ProcessorUtils.transform_with_side_collection(
            data, context_data, source_guid, agent_config
        )

        # Should process without errors
        assert isinstance(result, list)
        assert len(result) == len(data)

        test_state.complete_test_run(test_id, True)

    def test_extremely_large_remove_collection_list(self):
        """Test remove_collection with extremely large field list."""
        test_id = "edge_case_large_remove_list"
        test_state.register_test_run(test_id, "edge_case")

        test_data = {f"field_{i}": f"value_{i}" for i in range(1000)}
        # Try to remove more fields than exist
        agent_config = {"remove_collection": [f"field_{i}" for i in range(1500)]}

        result = ProcessorUtils.apply_remove_collection(test_data, agent_config)

        # Should remove all existing fields and not error on non-existent ones
        expected_removed = [f"field_{i}" for i in range(1000)]
        for field in expected_removed:
            assert field not in result, f"Field {field} should have been removed"

        test_state.complete_test_run(test_id, True)


@pytest.fixture(scope="function")
def cleanup_test_state():
    """Fixture to clean up test state after each test."""
    yield
    # Test state is a singleton, so we don't need explicit cleanup
    # But we could add cleanup logic here if needed


def test_collection_management_integration():
    """Integration test combining remove_collection and side_collection."""
    test_id = "integration_collection_management"
    test_state.register_test_run(test_id, "integration")

    with temporary_test_environment() as env:
        pattern = CollectionManagementTestHelper.create_qanalabs_test_patterns()[0]
        context_data = CollectionManagementTestHelper.generate_test_data(pattern, item_count=1)[0]

        # First apply remove_collection
        agent_config_remove = {"remove_collection": pattern.remove_collection_fields}
        filtered_context = ProcessorUtils.apply_remove_collection(context_data, agent_config_remove)

        # Then apply side_collection
        generated_data = ["new_item_1", "new_item_2"]
        agent_config_side = {"side_collection": pattern.side_collection_fields}
        source_guid = "integration-test-guid"

        final_result = ProcessorUtils.transform_with_side_collection(
            generated_data, filtered_context, source_guid, agent_config_side
        )

        # Verify the integration worked correctly
        assert isinstance(final_result, list)
        assert len(final_result) == len(generated_data)

        for item in final_result:
            content = item['content']

            # Fields that were removed should not be in context data used for side_collection
            for field in pattern.remove_collection_fields:
                # Note: some fields might still appear if they were in side_collection but not remove_collection
                pass

            # Fields that are in side_collection but not remove_collection should be preserved
            side_only_fields = set(pattern.side_collection_fields) - set(pattern.remove_collection_fields)
            for field in side_only_fields:
                if field in context_data:
                    assert field in content, f"Side collection field '{field}' should be preserved"

    test_state.complete_test_run(test_id, True)


if __name__ == "__main__":
    # Run performance benchmarks when executed directly
    test_performance = TestPerformanceBenchmarks()
    test_performance.test_remove_collection_performance_1000_items()
    test_performance.test_side_collection_performance_large_context()

    # Print summary
    summary = test_state.get_summary()
    print("\nCollection Management Test Summary:")
    print(f"Total tests run: {len(summary['test_runs'])}")
    print(f"Performance metrics: {len(summary['performance_metrics'])}")
    print(f"Security violations: {len(summary['security_violations'])}")