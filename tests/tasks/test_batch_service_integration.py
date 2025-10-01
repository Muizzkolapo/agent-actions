"""
Integration tests for BatchService filtering behavior.
These tests verify the end-to-end behavior of filter vs skip behaviors.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from agent_actions.tasks.services.batch_service import BatchService


class TestBatchServiceIntegration:
    """Integration tests for BatchService WHERE clause behaviors."""

    @pytest.fixture
    def batch_service(self):
        """Create a BatchService instance for testing."""
        return BatchService()

    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary output directory for tests."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    def test_filter_behavior_returns_empty_data(self, batch_service, temp_output_dir):
        """
        Integration test: Filter behavior with no matching items returns empty data.
        This simulates the condition '1 == 2' which always evaluates to False.
        """

        # Mock the filter service to always return False
        mock_filter_service = Mock()
        mock_filter_service.filter_item.return_value = Mock(
            success=True,
            matched=False,  # Always False - no items match
            data={},
            error=None
        )

        with patch('agent_actions.core.parser.where_parser.get_global_filter', return_value=mock_filter_service):
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

            data = [
                {"target_id": "test1", "content": "should be filtered"},
                {"target_id": "test2", "content": "should also be filtered"}
            ]

            # This should return empty passthrough data
            result = batch_service.submit_batch_job_from_data(
                agent_config, "test_batch", data, temp_output_dir
            )

            # Verify result structure
            assert isinstance(result, dict)
            assert result.get("type") == "passthrough"
            assert result.get("data") == []  # Empty array for filter behavior
            assert result.get("output_directory") == temp_output_dir

    def test_skip_behavior_returns_passthrough_data(self, batch_service, temp_output_dir):
        """
        Integration test: Skip behavior with no matching items returns passthrough data.
        This simulates the condition '1 == 2' which always evaluates to False.
        """

        # Mock the filter service to always return False
        mock_filter_service = Mock()
        mock_filter_service.filter_item.return_value = Mock(
            success=True,
            matched=False,  # Always False - no items match
            data={},
            error=None
        )

        with patch('agent_actions.core.parser.where_parser.get_global_filter', return_value=mock_filter_service):
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

            data = [
                {"target_id": "test1", "content": "should be skipped"},
                {"target_id": "test2", "content": "should also be skipped"}
            ]

            # This should return passthrough data with skipped items
            result = batch_service.submit_batch_job_from_data(
                agent_config, "test_batch", data, temp_output_dir
            )

            # Verify result structure
            assert isinstance(result, dict)
            assert result.get("type") == "passthrough"
            assert len(result.get("data", [])) == 2  # Both items passed through

            # Verify each item has skip metadata
            for item in result.get("data", []):
                assert item.get("metadata", {}).get("skipped_by_where_clause") is True
                assert item.get("metadata", {}).get("agent_type") == "passthrough"
                # Verify internal filter status is cleaned up
                assert "_batch_filter_status" not in item

    def test_workflow_output_format_consistency(self, batch_service, temp_output_dir):
        """
        Test that both filter and skip behaviors return the same passthrough format.
        This ensures the workflow can handle both consistently.
        """

        mock_filter_service = Mock()
        mock_filter_service.filter_item.return_value = Mock(
            success=True, matched=False, data={}, error=None
        )

        with patch('agent_actions.core.parser.where_parser.get_global_filter', return_value=mock_filter_service):
            data = [{"target_id": "test1", "content": "test"}]

            # Test filter behavior
            filter_config = {
                "where_clause": {"clause": "1 == 2", "scope": "item", "behavior": "filter"},
                "model_vendor": "openai",
                "model_name": "gpt-4o-mini",
                "api_key": "OPENAI_API_KEY",
                "schema": {"result": "string"}
            }

            filter_result = batch_service.submit_batch_job_from_data(
                filter_config, "test_batch", data, temp_output_dir
            )

            # Test skip behavior
            skip_config = {
                "where_clause": {"clause": "1 == 2", "scope": "item", "behavior": "skip"},
                "model_vendor": "openai",
                "model_name": "gpt-4o-mini",
                "api_key": "OPENAI_API_KEY",
                "schema": {"result": "string"}
            }

            skip_result = batch_service.submit_batch_job_from_data(
                skip_config, "test_batch", data, temp_output_dir
            )

            # Both should return passthrough format
            assert filter_result.get("type") == "passthrough"
            assert skip_result.get("type") == "passthrough"

            # Both should have same output directory
            assert filter_result.get("output_directory") == temp_output_dir
            assert skip_result.get("output_directory") == temp_output_dir

            # Different data content (empty vs passthrough)
            assert len(filter_result.get("data", [])) == 0
            assert len(skip_result.get("data", [])) == 1

    def test_filtered_items_excluded_from_batch_results(self, batch_service):
        """
        Test that filtered items are completely excluded from batch result processing.
        """

        # Setup context map with mixed statuses
        batch_service.context_map = {
            "included_item": {
                "target_id": "included_item",
                "source_guid": "included_item",
                "content": "should be included",
                "_batch_filter_status": "included"
            },
            "filtered_item": {
                "target_id": "filtered_item",
                "source_guid": "filtered_item",
                "content": "should be filtered out",
                "_batch_filter_status": "filtered"
            },
            "skipped_item": {
                "target_id": "skipped_item",
                "source_guid": "skipped_item",
                "content": "should be passed through",
                "_batch_filter_status": "skipped"
            }
        }

        # Mock batch results (only for included items)
        from agent_actions.integrations.providers.base import BatchResult
        batch_results = [
            BatchResult(
                custom_id="included_item",
                success=True,
                content={"result": "processed"},
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
            output_directory="/tmp/test"
        )

        # Should have 2 items: 1 processed + 1 skipped (filtered item excluded)
        assert len(processed_data) == 2

        source_guids = [item.get("source_guid") for item in processed_data]
        assert "included_item" in source_guids    # Processed
        assert "skipped_item" in source_guids     # Passed through
        assert "filtered_item" not in source_guids  # Completely excluded

        # Verify skipped item has correct metadata
        skipped_items = [
            item for item in processed_data
            if item.get("metadata", {}).get("skipped_by_conditional") is True
        ]
        assert len(skipped_items) == 1
        assert skipped_items[0]["source_guid"] == "skipped_item"