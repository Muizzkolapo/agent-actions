"""
Integration tests for BatchService filtering behavior.
These tests verify the end-to-end behavior of filter vs skip behaviors.
"""
import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock, patch
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.llm_invocation.realtime.providers.base import BatchResult

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
        mock_filter_service = Mock()
        mock_filter_service.filter_item.return_value = Mock(success=True, matched=False, data={}, error=None)
        with patch('agent_actions.core.parser.where_parser.get_global_filter', return_value=mock_filter_service):
            agent_config = {'where_clause': {'clause': '1 == 2', 'scope': 'item', 'behavior': 'filter'}, 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY', 'schema': {'result': 'string'}}
            data = [{'target_id': 'test1', 'content': 'should be filtered'}, {'target_id': 'test2', 'content': 'should also be filtered'}]
            result = batch_service.submit_batch_job_from_data(agent_config, 'test_batch', data, temp_output_dir)
            assert isinstance(result, dict)
            assert result.get('type') == 'passthrough'
            assert result.get('data') == []
            assert result.get('output_directory') == temp_output_dir

    def test_skip_behavior_returns_passthrough_data(self, batch_service, temp_output_dir):
        """
        Integration test: Skip behavior with no matching items returns passthrough data.
        This simulates the condition '1 == 2' which always evaluates to False.
        """
        mock_filter_service = Mock()
        mock_filter_service.filter_item.return_value = Mock(success=True, matched=False, data={}, error=None)
        with patch('agent_actions.core.parser.where_parser.get_global_filter', return_value=mock_filter_service):
            agent_config = {'where_clause': {'clause': '1 == 2', 'scope': 'item', 'behavior': 'skip'}, 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY', 'schema': {'result': 'string'}}
            data = [{'target_id': 'test1', 'content': 'should be skipped'}, {'target_id': 'test2', 'content': 'should also be skipped'}]
            result = batch_service.submit_batch_job_from_data(agent_config, 'test_batch', data, temp_output_dir)
            assert isinstance(result, dict)
            assert result.get('type') == 'passthrough'
            assert len(result.get('data', [])) == 2
            for item in result.get('data', []):
                assert item.get('metadata', {}).get('skipped_by_where_clause') is True
                assert item.get('metadata', {}).get('agent_type') == 'passthrough'
                assert '_batch_filter_status' not in item

    def test_workflow_output_format_consistency(self, batch_service, temp_output_dir):
        """
        Test that both filter and skip behaviors return the same passthrough format.
        This ensures the workflow can handle both consistently.
        """
        mock_filter_service = Mock()
        mock_filter_service.filter_item.return_value = Mock(success=True, matched=False, data={}, error=None)
        with patch('agent_actions.core.parser.where_parser.get_global_filter', return_value=mock_filter_service):
            data = [{'target_id': 'test1', 'content': 'test'}]
            filter_config = {'where_clause': {'clause': '1 == 2', 'scope': 'item', 'behavior': 'filter'}, 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY', 'schema': {'result': 'string'}}
            filter_result = batch_service.submit_batch_job_from_data(filter_config, 'test_batch', data, temp_output_dir)
            skip_config = {'where_clause': {'clause': '1 == 2', 'scope': 'item', 'behavior': 'skip'}, 'model_vendor': 'openai', 'model_name': 'gpt-4o-mini', 'api_key': 'OPENAI_API_KEY', 'schema': {'result': 'string'}}
            skip_result = batch_service.submit_batch_job_from_data(skip_config, 'test_batch', data, temp_output_dir)
            assert filter_result.get('type') == 'passthrough'
            assert skip_result.get('type') == 'passthrough'
            assert filter_result.get('output_directory') == temp_output_dir
            assert skip_result.get('output_directory') == temp_output_dir
            assert len(filter_result.get('data', [])) == 0
            assert len(skip_result.get('data', [])) == 1

    def test_filtered_items_excluded_from_batch_results(self, batch_service):
        """
        Test that filtered items are completely excluded from batch result processing.
        """
        batch_service.context_map = {'included_item': {'target_id': 'included_item', 'source_guid': 'included_item', 'content': 'should be included', '_batch_filter_status': 'included'}, 'filtered_item': {'target_id': 'filtered_item', 'source_guid': 'filtered_item', 'content': 'should be filtered out', '_batch_filter_status': 'filtered'}, 'skipped_item': {'target_id': 'skipped_item', 'source_guid': 'skipped_item', 'content': 'should be passed through', '_batch_filter_status': 'skipped'}}
        batch_results = [BatchResult(custom_id='included_item', success=True, content={'result': 'processed'}, usage={'tokens': 10}, metadata={}, error=None)]
        processed_data = batch_service._convert_batch_results_to_workflow_format(batch_results, observe=[], context_map=batch_service.context_map, output_directory='/tmp/test')
        assert len(processed_data) == 2
        source_guids = [item.get('source_guid') for item in processed_data]
        assert 'included_item' in source_guids
        assert 'skipped_item' in source_guids
        assert 'filtered_item' not in source_guids
        skipped_items = [item for item in processed_data if item.get('metadata', {}).get('skipped_by_conditional') is True]
        assert len(skipped_items) == 1
        assert skipped_items[0]['source_guid'] == 'skipped_item'

class TestBatchValidationAndRetry:
    """Tests for batch result validation and retry logic."""

    @pytest.fixture
    def batch_service(self):
        """Create a BatchService instance for testing."""
        return BatchService()

    @pytest.fixture
    def temp_batch_dir(self):
        """Create a temporary batch directory for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            batch_dir = Path(temp_dir) / 'batch'
            batch_dir.mkdir(parents=True, exist_ok=True)
            yield batch_dir

    @pytest.fixture
    def mock_provider(self):
        """Mock batch provider for testing."""
        provider = Mock()
        provider.prepare_tasks = Mock(return_value=[{'custom_id': 'test'}])
        provider.submit_batch = Mock(return_value='batch_123')
        provider.retrieve_results = Mock(return_value=[])
        return provider

    def create_test_context_map(self, count=10, status='included'):
        """Helper to create test context map."""
        return {f'rec_{i}': {'target_id': f'rec_{i}', 'source_guid': f'rec_{i}', 'content': f'content_{i}', '_batch_filter_status': status} for i in range(count)}

    def create_test_batch_results(self, custom_ids):
        """Helper to create test batch results."""
        return [BatchResult(custom_id=str(custom_id), success=True, content={'result': f'processed_{custom_id}'}, usage={'tokens': 10}, metadata={}, error=None) for custom_id in custom_ids]

    def test_collect_expected_custom_ids_filters_by_status(self, batch_service):
        """Test that _collect_expected_custom_ids only returns 'included' records."""
        context_map = {'rec_1': {'_batch_filter_status': 'included'}, 'rec_2': {'_batch_filter_status': 'filtered'}, 'rec_3': {'_batch_filter_status': 'skipped'}, 'rec_4': {'_batch_filter_status': 'included'}}
        expected_ids = batch_service._collect_expected_custom_ids(context_map)
        assert expected_ids == {'rec_1', 'rec_4'}
        assert 'rec_2' not in expected_ids
        assert 'rec_3' not in expected_ids

    def test_collect_expected_custom_ids_returns_strings(self, batch_service):
        """Test that _collect_expected_custom_ids normalizes IDs to strings."""
        context_map = {1: {'_batch_filter_status': 'included'}, '2': {'_batch_filter_status': 'included'}, 3: {'_batch_filter_status': 'included'}}
        expected_ids = batch_service._collect_expected_custom_ids(context_map)
        assert all((isinstance(id, str) for id in expected_ids))
        assert expected_ids == {'1', '2', '3'}

    def test_collect_result_custom_ids_skips_error_placeholders(self, batch_service):
        """Test that _collect_result_custom_ids excludes error_line_* placeholders."""
        batch_results = [BatchResult(custom_id='rec_1', success=True, content={}, error=None), BatchResult(custom_id='error_line_5', success=False, content={}, error='Parse error'), BatchResult(custom_id='rec_2', success=True, content={}, error=None)]
        result_ids = batch_service._collect_result_custom_ids(batch_results)
        assert result_ids == {'rec_1', 'rec_2'}
        assert 'error_line_5' not in result_ids

    def test_collect_result_custom_ids_handles_none(self, batch_service):
        """Test that _collect_result_custom_ids safely handles None custom_ids."""
        batch_results = [BatchResult(custom_id='rec_1', success=True, content={}, error=None), BatchResult(custom_id=None, success=False, content={}, error='No ID'), BatchResult(custom_id='rec_2', success=True, content={}, error=None)]
        result_ids = batch_service._collect_result_custom_ids(batch_results)
        assert result_ids == {'rec_1', 'rec_2'}
        assert None not in result_ids

    def test_post_processing_validation_catches_missing(self, batch_service):
        """Test that post-processing validation detects missing records."""
        context_map = self.create_test_context_map(count=3, status='included')
        batch_results = self.create_test_batch_results(['rec_0', 'rec_1'])
        from agent_actions.shared.exceptions import ProcessingError
        with pytest.raises(ProcessingError) as exc_info:
            batch_service._convert_batch_results_to_workflow_format(batch_results, observe=[], context_map=context_map, output_directory='/tmp/test')
        error = exc_info.value
        assert hasattr(error, 'context')
        assert error.context.get('validation_stage') == 'post_processing'
        assert 'rec_2' in error.context.get('missing_custom_ids', [])
        assert error.context.get('missing_count') == 1

    def test_load_retry_config_uses_default(self, batch_service):
        """Test that _load_retry_config uses default when not configured."""
        agent_config = {'model_name': 'gpt-4'}
        max_retry_depth = batch_service._load_retry_config(agent_config)
        assert max_retry_depth == 2

    def test_load_retry_config_uses_custom_depth(self, batch_service):
        """Test that _load_retry_config uses configured value."""
        agent_config = {'model_name': 'gpt-4', 'batch_retry': {'max_retry_depth': 5}}
        max_retry_depth = batch_service._load_retry_config(agent_config)
        assert max_retry_depth == 5

    def test_load_retry_config_validates_range(self, batch_service):
        """Test that _load_retry_config validates value range."""
        agent_config_negative = {'batch_retry': {'max_retry_depth': -1}}
        max_depth = batch_service._load_retry_config(agent_config_negative)
        assert max_depth == 2
        agent_config_high = {'batch_retry': {'max_retry_depth': 15}}
        max_depth = batch_service._load_retry_config(agent_config_high)
        assert max_depth == 2
        agent_config_string = {'batch_retry': {'max_retry_depth': '2'}}
        max_depth = batch_service._load_retry_config(agent_config_string)
        assert max_depth == 2

    def test_load_retry_config_with_none(self, batch_service):
        """Test that _load_retry_config handles None agent_config."""
        max_retry_depth = batch_service._load_retry_config(None)
        assert max_retry_depth == 2

    def test_create_retry_manifest_structure(self, batch_service, temp_batch_dir):
        """Test that _create_retry_manifest creates proper structure."""
        parent_batch_id = 'batch_parent_123'
        retry_batch_id = 'batch_retry_456'
        missing_ids = {'rec_1', 'rec_2'}
        batch_service._create_retry_manifest(parent_batch_id=parent_batch_id, retry_batch_id=retry_batch_id, missing_custom_ids=missing_ids, retry_attempt=1, output_directory=str(temp_batch_dir.parent))
        manifest_file = temp_batch_dir / f'{parent_batch_id}_retry_manifest.json'
        assert manifest_file.exists()
        with open(manifest_file, 'r') as f:
            manifest = json.load(f)
        assert manifest['parent_batch_id'] == parent_batch_id
        assert manifest['total_retries'] == 1
        assert len(manifest['retry_attempts']) == 1
        assert manifest['retry_attempts'][0]['retry_batch_id'] == retry_batch_id
        assert manifest['retry_attempts'][0]['attempt_number'] == 1
        assert set(manifest['retry_attempts'][0]['missing_custom_ids']) == missing_ids

    def test_update_retry_manifest_adds_entry(self, batch_service, temp_batch_dir):
        """Test that _update_retry_manifest appends new retry attempts."""
        parent_batch_id = 'batch_parent_123'
        batch_service._create_retry_manifest(parent_batch_id=parent_batch_id, retry_batch_id='batch_retry_1', missing_custom_ids={'rec_1', 'rec_2'}, retry_attempt=1, output_directory=str(temp_batch_dir.parent))
        batch_service._update_retry_manifest(parent_batch_id=parent_batch_id, retry_batch_id='batch_retry_2', missing_custom_ids={'rec_1'}, retry_attempt=2, output_directory=str(temp_batch_dir.parent))
        manifest_file = temp_batch_dir / f'{parent_batch_id}_retry_manifest.json'
        with open(manifest_file, 'r') as f:
            manifest = json.load(f)
        assert manifest['total_retries'] == 2
        assert len(manifest['retry_attempts']) == 2
        assert manifest['retry_attempts'][1]['retry_batch_id'] == 'batch_retry_2'
        assert manifest['retry_attempts'][1]['attempt_number'] == 2

    def test_append_to_dlq_creates_jsonl(self, batch_service, temp_batch_dir):
        """Test that _append_to_dlq creates JSONL file."""
        context_map = self.create_test_context_map(count=2)
        missing_ids = {'rec_0', 'rec_1'}
        batch_service._append_to_dlq(missing_custom_ids=missing_ids, context_map=context_map, output_directory=str(temp_batch_dir.parent), parent_batch_id='batch_123', retry_attempt=2)
        dlq_file = temp_batch_dir / 'dead_letter_queue.jsonl'
        assert dlq_file.exists()
        with open(dlq_file, 'r') as f:
            lines = f.readlines()
        assert len(lines) == 2
        for line in lines:
            entry = json.loads(line)
            assert 'custom_id' in entry
            assert 'parent_batch_id' in entry
            assert 'archived_at' in entry
            assert 'reason' in entry
            assert entry['reason'] == 'max_retry_exceeded'

    def test_append_to_dlq_includes_metadata(self, batch_service, temp_batch_dir):
        """Test that DLQ entries include all required metadata."""
        context_map = {'rec_1': {'target_id': 'rec_1', 'content': 'test content', '_batch_filter_status': 'included'}}
        batch_service._append_to_dlq(missing_custom_ids={'rec_1'}, context_map=context_map, output_directory=str(temp_batch_dir.parent), parent_batch_id='batch_456', retry_attempt=3)
        dlq_file = temp_batch_dir / 'dead_letter_queue.jsonl'
        with open(dlq_file, 'r') as f:
            entry = json.loads(f.readline())
        assert entry['custom_id'] == 'rec_1'
        assert entry['parent_batch_id'] == 'batch_456'
        assert entry['retry_attempt'] == 3
        assert 'archived_at' in entry
        assert 'original_data' in entry
        assert entry['original_data']['target_id'] == 'rec_1'

    def test_mark_parent_batch_has_retry(self, batch_service, temp_batch_dir):
        """Test that _mark_parent_batch_has_retry updates registry."""
        registry_file = temp_batch_dir / '.batch_registry.json'
        registry = {'batch_file.json': {'batch_id': 'batch_parent_123', 'status': 'completed', 'has_retry_batch': False}}
        with open(registry_file, 'w') as f:
            json.dump(registry, f)
        batch_service._mark_parent_batch_has_retry(parent_batch_id='batch_parent_123', output_directory=str(temp_batch_dir.parent))
        with open(registry_file, 'r') as f:
            updated_registry = json.load(f)
        assert updated_registry['batch_file.json']['has_retry_batch'] is True

    def test_merge_batch_results_no_duplicates(self, batch_service):
        """Test that _merge_batch_results combines non-overlapping results."""
        parent_results = self.create_test_batch_results(['rec_1', 'rec_2', 'rec_3'])
        retry_results = [self.create_test_batch_results(['rec_4', 'rec_5'])]
        merged = batch_service._merge_batch_results(parent_results, retry_results)
        assert len(merged) == 5
        merged_ids = {r.custom_id for r in merged}
        assert merged_ids == {'rec_1', 'rec_2', 'rec_3', 'rec_4', 'rec_5'}

    def test_merge_prefers_retry_for_duplicates(self, batch_service):
        """Test that _merge_batch_results prefers retry result for duplicates."""
        parent_results = [BatchResult(custom_id='rec_1', content={'version': 'old'}, success=True, error=None)]
        retry_results = [[BatchResult(custom_id='rec_1', content={'version': 'new'}, success=True, error=None)]]
        merged = batch_service._merge_batch_results(parent_results, retry_results)
        assert len(merged) == 1
        assert merged[0].custom_id == 'rec_1'
        assert merged[0].content['version'] == 'new'

    def test_collect_retry_batches_finds_all(self, batch_service, temp_batch_dir):
        """Test that _collect_retry_batches finds all retry batches."""
        registry_file = temp_batch_dir / '.batch_registry.json'
        registry = {'batch_file.json': {'batch_id': 'batch_parent_123', 'retry_attempt': 0, 'parent_batch_id': None}, 'batch_file_retry_1.json': {'batch_id': 'batch_retry_1', 'retry_attempt': 1, 'parent_batch_id': 'batch_parent_123'}, 'batch_file_retry_2.json': {'batch_id': 'batch_retry_2', 'retry_attempt': 2, 'parent_batch_id': 'batch_parent_123'}}
        with open(registry_file, 'w') as f:
            json.dump(registry, f)
        retry_batches = batch_service._collect_retry_batches(parent_batch_id='batch_parent_123', output_directory=str(temp_batch_dir.parent))
        assert len(retry_batches) == 2
        assert retry_batches[0]['batch_id'] == 'batch_retry_1'
        assert retry_batches[1]['batch_id'] == 'batch_retry_2'
        assert retry_batches[0]['retry_attempt'] < retry_batches[1]['retry_attempt']