"""
Tests for BatchService WHERE clause filtering behaviors.
Tests both 'filter' and 'skip' behaviors to ensure correct data handling.
"""
import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import tempfile
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.llm_invocation.realtime.providers.base import BatchResult

class MockFilterService:
    """Mock filter service that simulates WHERE clause evaluation."""

    def filter_item(self, item_data, clause):
        """Simple mock that evaluates basic conditions."""
        if clause == '1 == 2':
            return MockFilterResult(success=True, matched=False, data=item_data)
        if 'questionable' in clause:
            if 'Low Value' in clause:
                matched = item_data.get('questionable') == 'Low Value'
                return MockFilterResult(success=True, matched=matched, data=item_data)
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
        return [{'target_id': 'item1', 'questionable': 'Low Value', 'content': 'Should be processed'}, {'target_id': 'item2', 'questionable': 'High Value', 'content': 'Should be filtered out'}, {'target_id': 'item3', 'questionable': 'Low Value', 'content': 'Should be processed'}]

    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary output directory for tests."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @patch('agent_actions.core.parser.where_parser.get_global_filter')
    @patch('agent_actions.tasks.services.batch_service.BatchProviderFactory')
    def test_filter_behavior_all_items_filtered(self, mock_factory, mock_get_filter, batch_service, temp_output_dir):
        """Test filter behavior when all items are filtered out (condition always false)."""
        mock_get_filter.return_value = MockFilterService()
        mock_provider = Mock()
        mock_provider.validate_config.return_value = (True, None)
        mock_provider.submit_batch.return_value = 'mock-batch-id'
        mock_factory.create_provider.return_value = mock_provider
        agent_config = {'where_clause': {'clause': '1 == 2', 'scope': 'item', 'behavior': 'filter'}, 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY', 'schema': {'result': 'string'}}
        data = [{'target_id': 'test1', 'content': 'test content'}]
        with patch.object(batch_service, 'prepare_batch_tasks_from_data', return_value=[]):
            result = batch_service.submit_batch_job_from_data(agent_config, 'test_batch', data, temp_output_dir)
        assert isinstance(result, dict)
        assert result.get('type') == 'passthrough'
        assert result.get('data') == []
        assert result.get('output_directory') == temp_output_dir
        mock_factory.create_provider.assert_not_called()
        mock_provider.submit_batch.assert_not_called()

    @patch('agent_actions.core.parser.where_parser.get_global_filter')
    @patch('agent_actions.tasks.services.batch_service.BatchProviderFactory')
    def test_filter_behavior_partial_filtering(self, mock_factory, mock_get_filter, batch_service, sample_data, temp_output_dir):
        """Test filter behavior with partial filtering (some items match, some don't)."""
        mock_get_filter.return_value = MockFilterService()
        mock_provider = Mock()
        mock_provider.submit_batch.return_value = 'batch_123'
        mock_provider.prepare_tasks.return_value = ['task1', 'task2']
        mock_provider.compile_schema.return_value = {'type': 'object'}
        mock_provider.validate_config.return_value = (True, None)
        mock_factory.create_provider.return_value = mock_provider
        agent_config = {'where_clause': {'clause': 'questionable == "Low Value"', 'scope': 'item', 'behavior': 'filter'}, 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY', 'schema': {'result': 'string'}}
        result = batch_service.submit_batch_job_from_data(agent_config, 'test_batch', sample_data, temp_output_dir)
        assert result == 'batch_123'
        mock_provider.submit_batch.assert_called_once()
        assert len(batch_service.context_map) == 3
        item1 = batch_service.context_map['item1']
        item2 = batch_service.context_map['item2']
        item3 = batch_service.context_map['item3']
        assert item1['_batch_filter_status'] == 'included'
        assert item2['_batch_filter_status'] == 'filtered'
        assert item3['_batch_filter_status'] == 'included'

    @patch('agent_actions.core.parser.where_parser.get_global_filter')
    @patch('agent_actions.tasks.services.batch_service.BatchProviderFactory')
    def test_skip_behavior_all_items_skipped(self, mock_factory, mock_get_filter, batch_service, temp_output_dir):
        """Test skip behavior when all items are skipped (condition always false)."""
        mock_get_filter.return_value = MockFilterService()
        mock_provider = Mock()
        mock_provider.validate_config.return_value = (True, None)
        mock_provider.submit_batch.return_value = 'mock-batch-id'
        mock_factory.create_provider.return_value = mock_provider
        agent_config = {'where_clause': {'clause': '1 == 2', 'scope': 'item', 'behavior': 'skip'}, 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY', 'schema': {'result': 'string'}}
        data = [{'target_id': 'test1', 'content': 'test content'}]
        mock_passthrough_data = {'type': 'passthrough', 'data': [{'target_id': 'test1', 'content': 'test content', 'metadata': {'skipped_by_where_clause': True, 'agent_type': 'passthrough'}}], 'output_directory': temp_output_dir}
        with patch.object(batch_service, 'prepare_batch_tasks_from_data', return_value=[]):
            with patch.object(batch_service, '_create_passthrough_data_from_context', return_value=mock_passthrough_data):
                result = batch_service.submit_batch_job_from_data(agent_config, 'test_batch', data, temp_output_dir)
        assert isinstance(result, dict)
        assert result.get('type') == 'passthrough'
        assert len(result.get('data')) == 1
        skipped_item = result.get('data')[0]
        assert skipped_item['target_id'] == 'test1'
        assert skipped_item['content'] == 'test content'
        assert skipped_item['metadata']['skipped_by_where_clause'] is True
        assert skipped_item['metadata']['agent_type'] == 'passthrough'
        mock_factory.create_provider.assert_not_called()
        mock_provider.submit_batch.assert_not_called()

    def test_convert_batch_results_excludes_filtered_items(self, batch_service, sample_data, temp_output_dir):
        """Test that _convert_batch_results_to_workflow_format excludes filtered items."""
        batch_service.context_map = {'item1': {**sample_data[0], '_batch_filter_status': 'included'}, 'item2': {**sample_data[1], '_batch_filter_status': 'filtered'}, 'item3': {**sample_data[2], '_batch_filter_status': 'included'}}
        batch_results = [BatchResult(custom_id='item1', success=True, content={'result': 'processed item1'}, usage={'tokens': 10}, metadata={}, error=None), BatchResult(custom_id='item3', success=True, content={'result': 'processed item3'}, usage={'tokens': 10}, metadata={}, error=None)]
        processed_data = batch_service._convert_batch_results_to_workflow_format(batch_results, observe=[], context_map=batch_service.context_map, output_directory=temp_output_dir)
        assert len(processed_data) == 2
        source_guids = [item.get('source_guid') for item in processed_data]
        assert 'item1' in source_guids
        assert 'item3' in source_guids
        assert 'item2' not in source_guids

    def test_convert_batch_results_includes_skipped_items(self, batch_service, sample_data, temp_output_dir):
        """Test that _convert_batch_results_to_workflow_format includes skipped items as passthrough."""
        batch_service.context_map = {'item1': {**sample_data[0], '_batch_filter_status': 'included'}, 'item2': {**sample_data[1], '_batch_filter_status': 'skipped'}, 'item3': {**sample_data[2], '_batch_filter_status': 'included'}}
        batch_results = [BatchResult(custom_id='item1', success=True, content={'result': 'processed item1'}, usage={'tokens': 10}, metadata={}, error=None), BatchResult(custom_id='item3', success=True, content={'result': 'processed item3'}, usage={'tokens': 10}, metadata={}, error=None)]
        processed_data = batch_service._convert_batch_results_to_workflow_format(batch_results, observe=[], context_map=batch_service.context_map, output_directory=temp_output_dir)
        assert len(processed_data) == 3
        skipped_items = [item for item in processed_data if item.get('metadata', {}).get('skipped_by_conditional') is True]
        assert len(skipped_items) == 1
        skipped_item = skipped_items[0]
        assert skipped_item['source_guid'] == 'item2'
        assert skipped_item['metadata']['agent_type'] == 'passthrough'

    @patch('agent_actions.tasks.services.batch_service.BatchProviderFactory')
    def test_legacy_conditional_clause_compatibility(self, mock_factory, batch_service, temp_output_dir):
        """Test that conditional_clause works with UDF registry and marks items as skipped."""
        mock_provider = Mock()
        mock_provider.validate_config.return_value = (True, None)
        mock_provider.compile_schema.return_value = {'type': 'object'}
        mock_provider.prepare_tasks.return_value = ['task1']
        mock_factory.create_provider.return_value = mock_provider
        agent_config = {'conditional_clause': 'test_function', 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY', 'schema': {'result': 'string'}}
        data = [{'target_id': 'item1', 'process': True, 'content': 'should process'}, {'target_id': 'item2', 'process': False, 'content': 'should skip'}]
        with patch('agent_actions.core.udf_registry.get_udf') as mock_get_udf:
            mock_test_func = Mock(side_effect=lambda data, **kwargs: data.get('process', True))
            mock_get_udf.return_value = mock_test_func
            tasks = batch_service.prepare_batch_tasks_from_data(agent_config, data)
            assert tasks is not None
            assert batch_service.context_map['item1']['_batch_filter_status'] == 'included'
            assert batch_service.context_map['item2']['_batch_filter_status'] == 'skipped'