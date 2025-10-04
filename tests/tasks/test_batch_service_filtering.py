"""
Tests for BatchService WHERE clause filtering behaviors.
Tests both 'filter' and 'skip' behaviors to ensure correct data handling.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import tempfile

from agent_actions.tasks.services.batch_service import BatchService
from agent_actions.integrations.providers.base import BatchResult


class MockFilterService:
    """Mock filter service that simulates WHERE clause evaluation."""

    def filter_item(self, item_data, clause):
        """Simple mock that evaluates basic conditions."""
        # Handle the test condition "1 == 2" (always False)
        if clause == "1 == 2":
            return MockFilterResult(success=True, matched=False, data=item_data)

        # Handle questionable field conditions
        if "questionable" in clause:
            if "Low Value" in clause:
                matched = item_data.get("questionable") == "Low Value"
                return MockFilterResult(success=True, matched=matched, data=item_data)

        # Default to True for unknown conditions
        return MockFilterResult(success=True, matched=True, data=item_data)


class MockFilterResult:
    """Mock filter result object."""

    def __init__(self, success, matched, data, error=None):
        self.success = success
        self.matched = matched
        self.data = data
        self.error = error


class TestBatchServiceFiltering:
    """Test suite for BatchService WHERE clause filtering."""

    @pytest.fixture
    def batch_service(self):
        """Create a BatchService instance for testing."""
        return BatchService()

    @pytest.fixture
    def sample_data(self):
        """Sample test data with different questionable values."""
        return [
            {
                "target_id": "item1",
                "questionable": "Low Value",
                "content": "Should be processed"
            },
            {
                "target_id": "item2",
                "questionable": "High Value",
                "content": "Should be filtered out"
            },
            {
                "target_id": "item3",
                "questionable": "Low Value",
                "content": "Should be processed"
            }
        ]

    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary output directory for tests."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @patch('agent_actions.core.parser.where_parser.get_global_filter')
    @patch('agent_actions.tasks.services.batch_service.BatchProviderFactory')
    def test_filter_behavior_all_items_filtered(self, mock_factory, mock_get_filter, batch_service, temp_output_dir):
        """Test filter behavior when all items are filtered out (condition always false)."""

        # Setup mocks
        mock_get_filter.return_value = MockFilterService()
        mock_provider = Mock()
        mock_provider.validate_config.return_value = (True, None)
        mock_provider.submit_batch.return_value = "mock-batch-id"
        mock_factory.create_provider.return_value = mock_provider

        # Agent config with filter behavior and condition that's always false
        agent_config = {
            "where_clause": {
                "clause": "1 == 2",
                "scope": "item",
                "behavior": "filter"
            },
            "model_vendor": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": "OPENAI_API_KEY",
            "schema": {"result": "string"}
        }

        data = [{"target_id": "test1", "content": "test content"}]

        # Mock prepare_batch_tasks_from_data to return empty list (all items filtered)
        with patch.object(batch_service, 'prepare_batch_tasks_from_data', return_value=[]):
            # Call submit_batch_job_from_data
            result = batch_service.submit_batch_job_from_data(
                agent_config,
                "test_batch",
                data,
                temp_output_dir
            )

        # Should return passthrough data with empty array
        assert isinstance(result, dict)
        assert result.get("type") == "passthrough"
        assert result.get("data") == []
        assert result.get("output_directory") == temp_output_dir

        # Verify no batch was submitted - provider should not be created when no tasks
        mock_factory.create_provider.assert_not_called()
        mock_provider.submit_batch.assert_not_called()

    @patch('agent_actions.core.parser.where_parser.get_global_filter')
    @patch('agent_actions.tasks.services.batch_service.BatchProviderFactory')
    def test_filter_behavior_partial_filtering(self, mock_factory, mock_get_filter, batch_service, sample_data, temp_output_dir):
        """Test filter behavior with partial filtering (some items match, some don't)."""

        # Setup mocks
        mock_get_filter.return_value = MockFilterService()
        mock_provider = Mock()
        mock_provider.submit_batch.return_value = "batch_123"
        mock_provider.prepare_tasks.return_value = ["task1", "task2"]
        mock_provider.compile_schema.return_value = {"type": "object"}
        mock_provider.validate_config.return_value = (True, None)
        mock_factory.create_provider.return_value = mock_provider

        # Agent config filtering for "Low Value" items only
        agent_config = {
            "where_clause": {
                "clause": 'questionable == "Low Value"',
                "scope": "item",
                "behavior": "filter"
            },
            "model_vendor": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": "OPENAI_API_KEY",
            "schema": {"result": "string"}
        }

        # Call submit_batch_job_from_data
        result = batch_service.submit_batch_job_from_data(
            agent_config,
            "test_batch",
            sample_data,
            temp_output_dir
        )

        # Should return a batch job ID (normal batch processing)
        assert result == "batch_123"

        # Verify batch was submitted with only matching items
        mock_provider.submit_batch.assert_called_once()

        # Check that context map has correct filter statuses
        assert len(batch_service.context_map) == 3

        # Items with "Low Value" should be included, others filtered
        item1 = batch_service.context_map["item1"]
        item2 = batch_service.context_map["item2"]
        item3 = batch_service.context_map["item3"]

        assert item1["_batch_filter_status"] == "included"
        assert item2["_batch_filter_status"] == "filtered"
        assert item3["_batch_filter_status"] == "included"

    @patch('agent_actions.core.parser.where_parser.get_global_filter')
    @patch('agent_actions.tasks.services.batch_service.BatchProviderFactory')
    def test_skip_behavior_all_items_skipped(self, mock_factory, mock_get_filter, batch_service, temp_output_dir):
        """Test skip behavior when all items are skipped (condition always false)."""

        # Setup mocks
        mock_get_filter.return_value = MockFilterService()
        mock_provider = Mock()
        mock_provider.validate_config.return_value = (True, None)
        mock_provider.submit_batch.return_value = "mock-batch-id"
        mock_factory.create_provider.return_value = mock_provider

        # Agent config with skip behavior and condition that's always false
        agent_config = {
            "where_clause": {
                "clause": "1 == 2",
                "scope": "item",
                "behavior": "skip"
            },
            "model_vendor": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": "OPENAI_API_KEY",
            "schema": {"result": "string"}
        }

        data = [{"target_id": "test1", "content": "test content"}]

        # Mock prepare_batch_tasks_from_data to return empty list (all items skipped)
        # and mock the passthrough data creation for skip behavior
        mock_passthrough_data = {
            "type": "passthrough",
            "data": [
                {
                    "target_id": "test1",
                    "content": "test content",
                    "metadata": {
                        "skipped_by_where_clause": True,
                        "agent_type": "passthrough"
                    }
                }
            ],
            "output_directory": temp_output_dir
        }

        with patch.object(batch_service, 'prepare_batch_tasks_from_data', return_value=[]):
            with patch.object(batch_service, '_create_passthrough_data_from_context', return_value=mock_passthrough_data):
                # Call submit_batch_job_from_data
                result = batch_service.submit_batch_job_from_data(
                    agent_config,
                    "test_batch",
                    data,
                    temp_output_dir
                )

        # Should return passthrough data with skipped items
        assert isinstance(result, dict)
        assert result.get("type") == "passthrough"
        assert len(result.get("data")) == 1

        # Check that skipped item has proper metadata
        skipped_item = result.get("data")[0]
        assert skipped_item["target_id"] == "test1"
        assert skipped_item["content"] == "test content"
        assert skipped_item["metadata"]["skipped_by_where_clause"] is True
        assert skipped_item["metadata"]["agent_type"] == "passthrough"

        # Verify no batch was submitted - provider should not be created when no tasks
        mock_factory.create_provider.assert_not_called()
        mock_provider.submit_batch.assert_not_called()

    def test_convert_batch_results_excludes_filtered_items(self, batch_service, sample_data, temp_output_dir):
        """Test that _convert_batch_results_to_workflow_format excludes filtered items."""

        # Setup context map with mixed filter statuses
        batch_service.context_map = {
            "item1": {**sample_data[0], "_batch_filter_status": "included"},
            "item2": {**sample_data[1], "_batch_filter_status": "filtered"},
            "item3": {**sample_data[2], "_batch_filter_status": "included"}
        }

        # Create mock batch results for included items only
        batch_results = [
            BatchResult(
                custom_id="item1",
                success=True,
                content={"result": "processed item1"},
                usage={"tokens": 10},
                metadata={},
                error=None
            ),
            BatchResult(
                custom_id="item3",
                success=True,
                content={"result": "processed item3"},
                usage={"tokens": 10},
                metadata={},
                error=None
            )
        ]

        # Convert to workflow format
        processed_data = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            side_collection=[],
            context_map=batch_service.context_map,
            output_directory=temp_output_dir
        )

        # Should only include processed items, filtered item should be completely excluded
        assert len(processed_data) == 2

        # Check that only item1 and item3 are present (item2 was filtered)
        source_guids = [item.get("source_guid") for item in processed_data]
        assert "item1" in source_guids
        assert "item3" in source_guids
        assert "item2" not in source_guids

    def test_convert_batch_results_includes_skipped_items(self, batch_service, sample_data, temp_output_dir):
        """Test that _convert_batch_results_to_workflow_format includes skipped items as passthrough."""

        # Setup context map with mixed skip statuses
        batch_service.context_map = {
            "item1": {**sample_data[0], "_batch_filter_status": "included"},
            "item2": {**sample_data[1], "_batch_filter_status": "skipped"},
            "item3": {**sample_data[2], "_batch_filter_status": "included"}
        }

        # Create mock batch results for included items only
        batch_results = [
            BatchResult(
                custom_id="item1",
                success=True,
                content={"result": "processed item1"},
                usage={"tokens": 10},
                metadata={},
                error=None
            ),
            BatchResult(
                custom_id="item3",
                success=True,
                content={"result": "processed item3"},
                usage={"tokens": 10},
                metadata={},
                error=None
            )
        ]

        # Convert to workflow format
        processed_data = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            side_collection=[],
            context_map=batch_service.context_map,
            output_directory=temp_output_dir
        )

        # Should include both processed items AND skipped item as passthrough
        assert len(processed_data) == 3

        # Find the skipped item
        skipped_items = [
            item for item in processed_data
            if item.get("metadata", {}).get("skipped_by_conditional") is True
        ]
        assert len(skipped_items) == 1

        skipped_item = skipped_items[0]
        assert skipped_item["source_guid"] == "item2"
        assert skipped_item["metadata"]["agent_type"] == "passthrough"

    @patch('agent_actions.tasks.services.batch_service.BatchProviderFactory')
    def test_legacy_conditional_clause_compatibility(self, mock_factory, batch_service, temp_output_dir):
        """Test that conditional_clause works with UDF registry and marks items as skipped."""

        # Setup mocks
        mock_provider = Mock()
        mock_provider.validate_config.return_value = (True, None)
        mock_provider.compile_schema.return_value = {"type": "object"}
        mock_provider.prepare_tasks.return_value = ["task1"]  # Only one task for item1
        mock_factory.create_provider.return_value = mock_provider

        # Agent config with conditional clause using simple function name
        agent_config = {
            "conditional_clause": "test_function",
            "model_vendor": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": "OPENAI_API_KEY",
            "schema": {"result": "string"}
        }

        data = [
            {"target_id": "item1", "process": True, "content": "should process"},
            {"target_id": "item2", "process": False, "content": "should skip"}
        ]

        # Mock the UDF registry to return our test function
        with patch('agent_actions.core.udf_registry.get_udf') as mock_get_udf:
            # Create a mock function that checks the 'process' field
            mock_test_func = Mock(side_effect=lambda data, **kwargs: data.get('process', True))
            mock_get_udf.return_value = mock_test_func

            # Call prepare_batch_tasks_from_data
            tasks = batch_service.prepare_batch_tasks_from_data(agent_config, data)

            # Should create tasks (filtered items don't prevent task creation in this test)
            assert tasks is not None

            # Check context map statuses
            assert batch_service.context_map["item1"]["_batch_filter_status"] == "included"
            assert batch_service.context_map["item2"]["_batch_filter_status"] == "skipped"