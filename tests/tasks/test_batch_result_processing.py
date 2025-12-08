"""
Comprehensive integration tests for batch result processing.

These tests capture the current behavior of _convert_batch_results_to_workflow_format
before refactoring. They serve as a safety net to ensure the refactored code
produces identical output.

Test Coverage:
- Success path: Processing successful batch results
- JSON mode handling: Both json_mode=True and json_mode=False
- Context scope passthrough: Pre-computed and fallback behaviors
- Lineage tracking: node_id and lineage generation
- Target ID and source_guid: Handling missing values
- Loop correlation ID: Adding correlation IDs based on record index
- Processing errors: Exceptions during transformation
- Batch result errors: Failed batch results
- Missing records: Records expected but not in results
- Filter status handling: filtered, skipped, included
- Passthrough items: Creating passthrough for missing/skipped records
"""
import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.llm_invocation.providers.base import BatchResult


class TestBatchResultProcessing:
    """Comprehensive tests for _convert_batch_results_to_workflow_format."""

    @pytest.fixture
    def batch_service(self):
        """Create a BatchService instance for testing."""
        return BatchService()

    @pytest.fixture
    def sample_agent_config(self):
        """Standard agent config for testing."""
        return {
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'json_mode': True,
            'schema': {'result': 'string'}
        }

    # ============================================================
    # SUCCESS PATH TESTS
    # ============================================================

    def test_successful_batch_result_basic(self, batch_service, sample_agent_config):
        """Test basic successful batch result processing."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                'content': 'original content',
                '_batch_filter_status': 'included'
            }
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'processed content'},
                usage={'tokens': 10},
                metadata={'model': 'gpt-4o-mini'},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_1_TestAgent',
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        item = processed[0]
        assert item['source_guid'] == 'src_1'
        assert item['target_id'] == 'rec_1'
        assert 'content' in item
        assert item['content']['result'] == 'processed content'
        assert item['metadata'] == {'model': 'gpt-4o-mini'}
        assert 'node_id' in item
        assert 'lineage' in item

    def test_successful_multiple_items(self, batch_service, sample_agent_config):
        """Test processing multiple successful batch results."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'},
            'rec_2': {'target_id': 'rec_2', 'source_guid': 'src_2', '_batch_filter_status': 'included'},
            'rec_3': {'target_id': 'rec_3', 'source_guid': 'src_3', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(custom_id='rec_1', success=True, content={'result': 'A'}, usage={}, metadata={}, error=None),
            BatchResult(custom_id='rec_2', success=True, content={'result': 'B'}, usage={}, metadata={}, error=None),
            BatchResult(custom_id='rec_3', success=True, content={'result': 'C'}, usage={}, metadata={}, error=None)
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_2_TestAgent',
            agent_config=sample_agent_config
        )

        assert len(processed) == 3
        results = [item['content']['result'] for item in processed]
        assert sorted(results) == ['A', 'B', 'C']

    def test_list_response_flattened(self, batch_service, sample_agent_config):
        """Test that list responses are properly flattened using DataTransformer."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        # Content is a list that should be flattened
        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content=[
                    {'result': 'item_1'},
                    {'result': 'item_2'},
                    {'result': 'item_3'}
                ],
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_1_TestAgent',
            agent_config=sample_agent_config
        )

        # Should have 3 items (one per list element)
        assert len(processed) == 3
        results = [item['content']['result'] for item in processed]
        assert results == ['item_1', 'item_2', 'item_3']

        # All should have same source_guid
        for item in processed:
            assert item['source_guid'] == 'src_1'

    # ============================================================
    # JSON MODE TESTS
    # ============================================================

    def test_json_mode_false_wraps_string_content(self, batch_service):
        """Test that json_mode=False wraps string content in output_field."""
        config = {
            'json_mode': False,
            'output_field': 'text_content'
        }

        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content='Plain text response',  # String, not dict
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_1_TestAgent',
            agent_config=config
        )

        assert len(processed) == 1
        assert 'content' in processed[0]
        assert processed[0]['content']['text_content'] == 'Plain text response'

    def test_json_mode_false_default_field_name(self, batch_service):
        """Test that json_mode=False uses 'content' as default output_field."""
        config = {
            'json_mode': False
            # No output_field specified, should default to 'content'
        }

        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content='Plain text',
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=config
        )

        assert 'content' in processed[0]
        assert isinstance(processed[0]['content'], dict)
        assert processed[0]['content']['content'] == 'Plain text'

    # ============================================================
    # CONTEXT SCOPE PASSTHROUGH TESTS
    # ============================================================

    def test_passthrough_pre_computed_fields(self, batch_service):
        """Test that pre-computed _passthrough_fields are merged into results."""
        config = {
            'json_mode': True,
            'context_scope': {
                'passthrough': ['metadata.user_id', 'timestamp']
            }
        }

        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                '_batch_filter_status': 'included',
                '_passthrough_fields': {
                    'user_id': 'user_123',
                    'timestamp': '2024-01-01T00:00:00Z'
                }
            }
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'processed'},
                usage={},
                metadata={},
                error=None
            )
        ]

        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.merge_passthrough_fields') as mock_merge:
            # Mock returns the list with passthrough merged
            mock_merge.return_value = [{'result': 'processed', 'user_id': 'user_123', 'timestamp': '2024-01-01T00:00:00Z'}]

            processed = batch_service._convert_batch_results_to_workflow_format(
                batch_results,
                context_map=context_map,
                agent_config=config
            )

            # Verify merge was called with stored passthrough fields
            mock_merge.assert_called_once()
            call_args = mock_merge.call_args
            assert call_args[0][1] == {'user_id': 'user_123', 'timestamp': '2024-01-01T00:00:00Z'}

    def test_passthrough_fallback_behavior(self, batch_service):
        """Test fallback to old passthrough behavior when _passthrough_fields not available."""
        config = {
            'json_mode': True,
            'context_scope': {
                'passthrough': ['user_id', 'timestamp']
            }
        }

        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                '_batch_filter_status': 'included',
                'content': {
                    'user_id': 'user_456',
                    'timestamp': '2024-02-01T00:00:00Z'
                }
                # No _passthrough_fields - triggers fallback
            }
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'processed'},
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=config
        )

        # Should still process successfully using fallback
        assert len(processed) == 1

    # ============================================================
    # LINEAGE TRACKING TESTS
    # ============================================================

    def test_lineage_with_node_directory(self, batch_service, sample_agent_config):
        """Test that lineage and node_id are generated from output_directory."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                '_batch_filter_status': 'included',
                'lineage': ['node_0_abc123']  # Existing lineage with proper node_ prefix
            }
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'data'},
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_5_MyAgent',
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        item = processed[0]
        assert 'node_id' in item
        assert item['node_id'].startswith('node_5_')
        assert 'lineage' in item
        assert isinstance(item['lineage'], list)
        # Should include both parent lineage and new node
        assert 'node_0_abc123' in item['lineage']
        assert item['node_id'] in item['lineage']
        assert len(item['lineage']) == 2

    def test_lineage_without_node_directory(self, batch_service, sample_agent_config):
        """Test that lineage is not added when output_directory is missing node pattern."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'data'},
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/regular_directory',  # No node_X pattern
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        item = processed[0]
        # node_id and lineage should not be added
        assert 'node_id' not in item or item.get('node_id') is None
        assert 'lineage' not in item or item.get('lineage') is None

    # ============================================================
    # TARGET ID AND SOURCE GUID TESTS
    # ============================================================

    def test_missing_target_id_generated(self, batch_service, sample_agent_config):
        """Test that missing target_id is generated."""
        context_map = {
            'rec_1': {
                # No target_id
                'source_guid': 'src_1',
                '_batch_filter_status': 'included'
            }
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'data'},
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        assert 'target_id' in processed[0]
        assert processed[0]['target_id'] is not None
        assert len(processed[0]['target_id']) > 0

    def test_missing_source_guid_defaults_to_custom_id(self, batch_service, sample_agent_config):
        """Test that missing source_guid defaults to custom_id."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                # No source_guid
                '_batch_filter_status': 'included'
            }
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'data'},
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        assert processed[0]['source_guid'] == 'rec_1'

    # ============================================================
    # LOOP CORRELATION ID TESTS
    # ============================================================

    def test_loop_correlation_id_added(self, batch_service):
        """Test that loop correlation ID is added when agent_config present."""
        config = {
            'json_mode': True,
            'loop': {
                'iteration_id': 'iter_123'
            }
        }

        context_map = {
            'rec_0': {'target_id': 'rec_0', 'source_guid': 'src_0', '_batch_filter_status': 'included'},
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(custom_id='rec_0', success=True, content={'result': 'A'}, usage={}, metadata={}, error=None),
            BatchResult(custom_id='rec_1', success=True, content={'result': 'B'}, usage={}, metadata={}, error=None)
        ]

        with patch('agent_actions.utilities.correlation.LoopIdGenerator.add_loop_correlation_id') as mock_add_corr:
            mock_add_corr.side_effect = lambda item, cfg, **kwargs: item  # Return unchanged

            processed = batch_service._convert_batch_results_to_workflow_format(
                batch_results,
                context_map=context_map,
                agent_config=config
            )

            # Should be called for each processed item
            assert mock_add_corr.call_count == 2

            # Verify record_index is passed correctly
            call_args_list = mock_add_corr.call_args_list
            # First call should have record_index=0, second should have record_index=1
            assert call_args_list[0][1]['record_index'] == 0
            assert call_args_list[1][1]['record_index'] == 1

    # ============================================================
    # ERROR HANDLING TESTS
    # ============================================================

    def test_processing_exception_creates_error_item(self, batch_service):
        """Test that exceptions during processing create error items."""
        config = {'json_mode': True}

        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        # Create a batch result with content that will cause processing error
        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'data'},  # This will be fine
                usage={},
                metadata={'test': 'meta'},
                error=None
            )
        ]

        # Mock DataTransformer.ensure_list to raise exception
        with patch('agent_actions.preprocessing.data_transformer.DataTransformer.ensure_list') as mock_ensure:
            mock_ensure.side_effect = ValueError("Simulated processing error")

            processed = batch_service._convert_batch_results_to_workflow_format(
                batch_results,
                context_map=context_map,
                agent_config=config
            )

            assert len(processed) == 1
            item = processed[0]
            assert 'error' in item
            assert 'Processing error' in item['error']
            assert 'Simulated processing error' in item['error']
            assert item['source_guid'] == 'src_1'
            assert 'raw_content' in item
            assert item['metadata'] == {'test': 'meta'}

    def test_batch_result_error_creates_error_item(self, batch_service, sample_agent_config):
        """Test that failed batch results create error items."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=False,
                content=None,
                usage={},
                metadata={'error_code': 'invalid_request'},
                error='Invalid schema format'
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        item = processed[0]
        assert 'error' in item
        assert item['error'] == 'Invalid schema format'
        assert item['source_guid'] == 'src_1'
        assert item['metadata'] == {'error_code': 'invalid_request'}

    def test_missing_context_map_entry_uses_custom_id(self, batch_service, sample_agent_config):
        """Test handling of batch result with missing context_map entry."""
        context_map = {
            'rec_2': {'target_id': 'rec_2', 'source_guid': 'src_2', '_batch_filter_status': 'filtered'}
        }

        # rec_1 is not in context_map
        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=False,
                content=None,
                usage={},
                metadata={},
                error='Not found'
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=sample_agent_config
        )

        # rec_2 is filtered so won't be in output
        # Only rec_1 (the error) should be present
        assert len(processed) == 1
        # Should use custom_id as fallback for source_guid
        assert processed[0]['source_guid'] == 'rec_1'
        assert 'error' in processed[0]

    # ============================================================
    # FILTER STATUS TESTS
    # ============================================================

    def test_filtered_items_excluded(self, batch_service, sample_agent_config):
        """Test that filtered items are completely excluded from results."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'},
            'rec_2': {'target_id': 'rec_2', 'source_guid': 'src_2', '_batch_filter_status': 'filtered'},
            'rec_3': {'target_id': 'rec_3', 'source_guid': 'src_3', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(custom_id='rec_1', success=True, content={'result': 'A'}, usage={}, metadata={}, error=None),
            BatchResult(custom_id='rec_3', success=True, content={'result': 'C'}, usage={}, metadata={}, error=None)
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=sample_agent_config
        )

        # Should only have 2 items (rec_1 and rec_3)
        assert len(processed) == 2
        source_guids = [item['source_guid'] for item in processed]
        assert 'src_1' in source_guids
        assert 'src_3' in source_guids
        assert 'src_2' not in source_guids  # Filtered item excluded

    def test_skipped_items_become_passthrough(self, batch_service, sample_agent_config):
        """Test that skipped items are converted to passthrough records."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', 'content': 'data1', '_batch_filter_status': 'included'},
            'rec_2': {'target_id': 'rec_2', 'source_guid': 'src_2', 'content': 'data2', '_batch_filter_status': 'skipped'}
        }

        # Only rec_1 has batch result
        batch_results = [
            BatchResult(custom_id='rec_1', success=True, content={'result': 'processed'}, usage={}, metadata={}, error=None)
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_3_TestAgent',
            agent_config=sample_agent_config
        )

        # Should have 2 items: rec_1 (processed) + rec_2 (passthrough)
        assert len(processed) == 2

        # Find the passthrough item
        passthrough_items = [item for item in processed if item.get('metadata', {}).get('skipped_by_conditional')]
        assert len(passthrough_items) == 1

        passthrough = passthrough_items[0]
        assert passthrough['source_guid'] == 'src_2'
        assert passthrough['target_id'] == 'rec_2'
        assert passthrough['content'] == 'data2'
        assert passthrough['metadata']['agent_type'] == 'passthrough'
        assert '_batch_filter_status' not in passthrough  # Should be removed

    def test_missing_included_items_become_passthrough(self, batch_service, sample_agent_config):
        """Test that missing 'included' items become passthrough records."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', 'content': 'data1', '_batch_filter_status': 'included'},
            'rec_2': {'target_id': 'rec_2', 'source_guid': 'src_2', 'content': 'data2', '_batch_filter_status': 'included'}
        }

        # Only rec_1 has batch result (rec_2 is missing)
        batch_results = [
            BatchResult(custom_id='rec_1', success=True, content={'result': 'processed'}, usage={}, metadata={}, error=None)
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_4_TestAgent',
            agent_config=sample_agent_config
        )

        # Should have 2 items: rec_1 (processed) + rec_2 (passthrough for missing)
        assert len(processed) == 2

        # Find the passthrough item
        passthrough_items = [item for item in processed if item.get('metadata', {}).get('skipped_by_conditional')]
        assert len(passthrough_items) == 1

        passthrough = passthrough_items[0]
        assert passthrough['source_guid'] == 'src_2'
        assert passthrough['target_id'] == 'rec_2'

    def test_batch_filter_status_removed_from_passthrough(self, batch_service, sample_agent_config):
        """Test that _batch_filter_status is removed from passthrough items."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                'content': 'data',
                '_batch_filter_status': 'skipped',
                'other_field': 'preserved'
            }
        }

        batch_results = []  # No results, so rec_1 becomes passthrough

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_1_TestAgent',
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        item = processed[0]
        assert '_batch_filter_status' not in item
        assert item['other_field'] == 'preserved'  # Other fields preserved

    # ============================================================
    # EDGE CASES
    # ============================================================

    def test_empty_batch_results(self, batch_service, sample_agent_config):
        """Test handling of empty batch results."""
        context_map = {}
        batch_results = []

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=sample_agent_config
        )

        assert processed == []

    def test_empty_context_map(self, batch_service, sample_agent_config):
        """Test handling of empty context map."""
        context_map = {}

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'data'},
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        # Should still process successfully

    def test_none_context_map(self, batch_service, sample_agent_config):
        """Test handling of None context map."""
        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'data'},
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=None,
            agent_config=sample_agent_config
        )

        assert len(processed) == 1

    def test_none_agent_config(self, batch_service):
        """Test handling of None agent_config."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'data'},
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=None
        )

        assert len(processed) == 1

    def test_none_output_directory(self, batch_service, sample_agent_config):
        """Test handling of None output_directory."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'data'},
                usage={},
                metadata={},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory=None,
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        # Should not have node_id or lineage
        assert 'node_id' not in processed[0] or processed[0].get('node_id') is None

    def test_none_custom_id_in_batch_result(self, batch_service, sample_agent_config):
        """Test handling of None custom_id in batch result."""
        context_map = {}

        batch_results = [
            BatchResult(
                custom_id=None,
                success=False,
                content=None,
                usage={},
                metadata={},
                error='No custom ID'
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            agent_config=sample_agent_config
        )

        assert len(processed) == 1
        # Should use 'unknown' as fallback
        assert processed[0]['source_guid'] == 'unknown'


class TestBatchResultProcessingSnapshot:
    """
    Snapshot tests to capture exact output format.
    These serve as regression tests during refactoring.
    """

    @pytest.fixture
    def batch_service(self):
        return BatchService()

    def test_complete_workflow_snapshot(self, batch_service):
        """
        Snapshot test: Capture complete workflow with all features.
        This is the "golden" test that must produce identical output after refactoring.
        """
        agent_config = {
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'json_mode': True,
            'schema': {'result': 'string'},
            'loop': {'iteration_id': 'iter_001'}
        }

        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                'content': 'original_1',
                '_batch_filter_status': 'included',
                'lineage': ['node_0_parent']
            },
            'rec_2': {
                'target_id': 'rec_2',
                'source_guid': 'src_2',
                'content': 'original_2',
                '_batch_filter_status': 'skipped'
            },
            'rec_3': {
                'target_id': 'rec_3',
                'source_guid': 'src_3',
                'content': 'original_3',
                '_batch_filter_status': 'filtered'
            },
            'rec_4': {
                'target_id': 'rec_4',
                'source_guid': 'src_4',
                'content': 'original_4',
                '_batch_filter_status': 'included'
                # rec_4 will be missing from results
            }
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'processed_1'},
                usage={'tokens': 10},
                metadata={'model': 'gpt-4o-mini'},
                error=None
            )
        ]

        processed = batch_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_7_TestAgent',
            agent_config=agent_config
        )

        # Verify structure (exact values tested in other tests)
        assert len(processed) == 3  # rec_1 (processed) + rec_2 (skipped) + rec_4 (missing)

        # rec_3 (filtered) should NOT be in output
        source_guids = [item['source_guid'] for item in processed]
        assert 'src_3' not in source_guids

        # rec_1 should be processed
        rec_1_items = [item for item in processed if item['source_guid'] == 'src_1']
        assert len(rec_1_items) == 1
        assert rec_1_items[0]['content']['result'] == 'processed_1'
        assert 'node_id' in rec_1_items[0]
        assert 'lineage' in rec_1_items[0]

        # rec_2 and rec_4 should be passthrough
        passthrough_items = [item for item in processed if item.get('metadata', {}).get('skipped_by_conditional')]
        assert len(passthrough_items) == 2
        passthrough_guids = [item['source_guid'] for item in passthrough_items]
        assert 'src_2' in passthrough_guids
        assert 'src_4' in passthrough_guids
