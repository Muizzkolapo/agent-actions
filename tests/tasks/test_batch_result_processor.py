"""
Tests for BatchResultProcessor.

These tests verify that the new pipeline-based processor produces identical
output to the original _convert_batch_results_to_workflow_format method.
"""
import pytest
from unittest.mock import patch, Mock
from agent_actions.llm_invocation.batch.batch_result_processor import (
    BatchResultProcessor, BatchProcessingContext
)
from agent_actions.llm_invocation.providers.base import BatchResult


class TestBatchResultProcessor:
    """Tests for BatchResultProcessor pipeline."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        return BatchResultProcessor()

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
    # STAGE 1: INITIALIZATION TESTS
    # ============================================================

    def test_stage_1_extracts_node_index(self, processor):
        """Test that stage 1 extracts node index from output_directory."""
        ctx = processor._stage_1_initialize_context(
            batch_results=[],
            context_map={},
            output_directory='/tmp/node_5_TestAgent',
            agent_config=None
        )

        assert ctx.node_idx == 5

    def test_stage_1_handles_no_node_pattern(self, processor):
        """Test that stage 1 handles directories without node pattern."""
        ctx = processor._stage_1_initialize_context(
            batch_results=[],
            context_map={},
            output_directory='/tmp/regular_directory',
            agent_config=None
        )

        assert ctx.node_idx is None

    def test_stage_1_extracts_config_values(self, processor):
        """Test that stage 1 extracts json_mode and output_field."""
        config = {
            'json_mode': False,
            'output_field': 'text_content'
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[],
            context_map={},
            output_directory=None,
            agent_config=config
        )

        assert ctx.json_mode is False
        assert ctx.output_field == 'text_content'

    def test_stage_1_defaults_config_values(self, processor):
        """Test that stage 1 uses defaults when config missing."""
        ctx = processor._stage_1_initialize_context(
            batch_results=[],
            context_map={},
            output_directory=None,
            agent_config=None
        )

        assert ctx.json_mode is True
        assert ctx.output_field == 'content'

    # ============================================================
    # STAGE 2: RECONCILIATION TESTS
    # ============================================================

    def test_stage_2_creates_reconciler(self, processor):
        """Test that stage 2 creates ResultReconciler."""
        ctx = BatchProcessingContext(
            batch_results=[],
            context_map={'rec_1': {}},
            output_directory=None,
            agent_config=None
        )

        ctx = processor._stage_2_reconcile(ctx)

        assert ctx.reconciler is not None
        assert ctx.reconciler.context_map == {'rec_1': {}}

    # ============================================================
    # STAGE 3-4: PROCESS RESULTS TESTS
    # ============================================================

    def test_stage_3_processes_successful_result(self, processor):
        """Test that stage 3 processes successful batch result."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                '_batch_filter_status': 'included'
            }
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[
                BatchResult(
                    custom_id='rec_1',
                    success=True,
                    content={'result': 'processed'},
                    usage={},
                    metadata={'model': 'test'},
                    error=None
                )
            ],
            context_map=context_map,
            output_directory='/tmp/node_1_Test',
            agent_config={'json_mode': True}
        )
        ctx = processor._stage_2_reconcile(ctx)
        ctx = processor._stage_3_4_process_results(ctx)

        assert len(ctx.processed_data) == 1
        assert ctx.success_count == 1
        assert ctx.error_count == 0
        assert 'rec_1' in ctx.reconciler._processed_ids

    def test_stage_4_processes_error_result(self, processor):
        """Test that stage 4 processes error batch result."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                '_batch_filter_status': 'included'
            }
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[
                BatchResult(
                    custom_id='rec_1',
                    success=False,
                    content=None,
                    usage={},
                    metadata={},
                    error='Invalid request'
                )
            ],
            context_map=context_map,
            output_directory=None,
            agent_config=None
        )
        ctx = processor._stage_2_reconcile(ctx)
        ctx = processor._stage_3_4_process_results(ctx)

        assert len(ctx.processed_data) == 1
        assert ctx.error_count == 1
        assert 'error' in ctx.processed_data[0]
        assert ctx.processed_data[0]['error'] == 'Invalid request'

    def test_processing_exception_creates_error_item(self, processor):
        """Test that exceptions during processing create error items."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[
                BatchResult(
                    custom_id='rec_1',
                    success=True,
                    content={'result': 'data'},
                    usage={},
                    metadata={'test': 'meta'},
                    error=None
                )
            ],
            context_map=context_map,
            output_directory=None,
            agent_config={'json_mode': True}
        )
        ctx = processor._stage_2_reconcile(ctx)

        # Mock DataTransformer.ensure_list to raise exception
        with patch('agent_actions.preprocessing.data_transformer.DataTransformer.ensure_list') as mock_ensure:
            mock_ensure.side_effect = ValueError("Simulated error")

            ctx = processor._stage_3_4_process_results(ctx)

            assert len(ctx.processed_data) == 1
            assert ctx.error_count == 1
            item = ctx.processed_data[0]
            assert 'error' in item
            assert 'Processing error' in item['error']
            assert 'raw_content' in item

    # ============================================================
    # STAGE 5: BUILD AGENT OUTPUT TESTS
    # ============================================================

    def test_json_mode_false_wraps_string(self, processor):
        """Test that json_mode=False wraps string content."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[
                BatchResult(
                    custom_id='rec_1',
                    success=True,
                    content='Plain text response',
                    usage={},
                    metadata={},
                    error=None
                )
            ],
            context_map=context_map,
            output_directory=None,
            agent_config={'json_mode': False, 'output_field': 'text_content'}
        )
        ctx = processor._stage_2_reconcile(ctx)
        ctx = processor._stage_3_4_process_results(ctx)

        assert len(ctx.processed_data) == 1
        assert 'content' in ctx.processed_data[0]
        assert ctx.processed_data[0]['content']['text_content'] == 'Plain text response'

    def test_lineage_tracking_added(self, processor):
        """Test that lineage and node_id are added when node_idx present."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                '_batch_filter_status': 'included',
                'lineage': ['node_0_parent']
            }
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[
                BatchResult(
                    custom_id='rec_1',
                    success=True,
                    content={'result': 'data'},
                    usage={},
                    metadata={},
                    error=None
                )
            ],
            context_map=context_map,
            output_directory='/tmp/node_5_Test',
            agent_config={'json_mode': True}
        )
        ctx = processor._stage_2_reconcile(ctx)
        ctx = processor._stage_3_4_process_results(ctx)

        assert len(ctx.processed_data) == 1
        item = ctx.processed_data[0]
        assert 'node_id' in item
        assert item['node_id'].startswith('node_5_')
        assert 'lineage' in item
        assert 'node_0_parent' in item['lineage']
        assert item['node_id'] in item['lineage']

    def test_loop_correlation_id_added(self, processor):
        """Test that loop correlation ID is added."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[
                BatchResult(
                    custom_id='rec_1',
                    success=True,
                    content={'result': 'data'},
                    usage={},
                    metadata={},
                    error=None
                )
            ],
            context_map=context_map,
            output_directory=None,
            agent_config={'json_mode': True, 'loop': {'iteration_id': 'iter_1'}}
        )
        ctx = processor._stage_2_reconcile(ctx)

        with patch('agent_actions.utilities.correlation.LoopIdGenerator.add_loop_correlation_id') as mock_add:
            mock_add.side_effect = lambda item, cfg, **kwargs: item

            ctx = processor._stage_3_4_process_results(ctx)

            mock_add.assert_called_once()
            call_kwargs = mock_add.call_args[1]
            assert call_kwargs['record_index'] == 0

    # ============================================================
    # STAGE 6: MERGE PASSTHROUGHS TESTS
    # ============================================================

    def test_stage_6_creates_passthroughs_for_skipped(self, processor):
        """Test that stage 6 creates passthrough for skipped records."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                'content': 'data1',
                '_batch_filter_status': 'included'
            },
            'rec_2': {
                'target_id': 'rec_2',
                'source_guid': 'src_2',
                'content': 'data2',
                '_batch_filter_status': 'skipped'
            }
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[
                BatchResult(
                    custom_id='rec_1',
                    success=True,
                    content={'result': 'processed'},
                    usage={},
                    metadata={},
                    error=None
                )
            ],
            context_map=context_map,
            output_directory='/tmp/node_1_Test',
            agent_config={'json_mode': True}
        )
        ctx = processor._stage_2_reconcile(ctx)
        ctx = processor._stage_3_4_process_results(ctx)
        ctx = processor._stage_6_merge_passthroughs(ctx)

        # Should have 2 items: rec_1 (processed) + rec_2 (passthrough)
        assert len(ctx.processed_data) == 2
        assert ctx.passthrough_count == 1

        # Find passthrough item
        passthrough_items = [
            item for item in ctx.processed_data
            if item.get('metadata', {}).get('skipped_by_conditional')
        ]
        assert len(passthrough_items) == 1
        assert passthrough_items[0]['source_guid'] == 'src_2'

    def test_stage_6_creates_passthroughs_for_missing(self, processor):
        """Test that stage 6 creates passthrough for missing 'included' records."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                '_batch_filter_status': 'included'
            },
            'rec_2': {
                'target_id': 'rec_2',
                'source_guid': 'src_2',
                'content': 'data2',
                '_batch_filter_status': 'included'
            }
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[
                BatchResult(
                    custom_id='rec_1',
                    success=True,
                    content={'result': 'processed'},
                    usage={},
                    metadata={},
                    error=None
                )
            ],
            context_map=context_map,
            output_directory='/tmp/node_1_Test',
            agent_config={'json_mode': True}
        )
        ctx = processor._stage_2_reconcile(ctx)
        ctx = processor._stage_3_4_process_results(ctx)
        ctx = processor._stage_6_merge_passthroughs(ctx)

        # Should have 2 items: rec_1 (processed) + rec_2 (passthrough for missing)
        assert len(ctx.processed_data) == 2
        assert ctx.passthrough_count == 1

        # Find passthrough item
        passthrough_items = [
            item for item in ctx.processed_data
            if item.get('metadata', {}).get('skipped_by_conditional')
        ]
        assert len(passthrough_items) == 1
        assert passthrough_items[0]['source_guid'] == 'src_2'

    def test_stage_6_excludes_filtered_records(self, processor):
        """Test that stage 6 excludes filtered records from passthrough."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'},
            'rec_2': {'target_id': 'rec_2', 'source_guid': 'src_2', '_batch_filter_status': 'filtered'}
        }

        ctx = processor._stage_1_initialize_context(
            batch_results=[
                BatchResult(
                    custom_id='rec_1',
                    success=True,
                    content={'result': 'processed'},
                    usage={},
                    metadata={},
                    error=None
                )
            ],
            context_map=context_map,
            output_directory=None,
            agent_config={'json_mode': True}
        )
        ctx = processor._stage_2_reconcile(ctx)
        ctx = processor._stage_3_4_process_results(ctx)
        ctx = processor._stage_6_merge_passthroughs(ctx)

        # Should only have 1 item (rec_1), rec_2 is filtered
        assert len(ctx.processed_data) == 1
        assert ctx.passthrough_count == 0

    # ============================================================
    # END-TO-END PIPELINE TESTS
    # ============================================================

    def test_process_complete_pipeline(self, processor, sample_agent_config):
        """Test complete pipeline execution."""
        context_map = {
            'rec_1': {
                'target_id': 'rec_1',
                'source_guid': 'src_1',
                'content': 'original_1',
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

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            output_directory='/tmp/node_1_TestAgent',
            agent_config=sample_agent_config
        )

        assert len(result) == 1
        item = result[0]
        assert item['source_guid'] == 'src_1'
        assert item['target_id'] == 'rec_1'
        assert item['content']['result'] == 'processed content'
        assert item['metadata'] == {'model': 'gpt-4o-mini'}
        assert 'node_id' in item
        assert 'lineage' in item

    def test_process_empty_inputs(self, processor):
        """Test pipeline with empty inputs."""
        result = processor.process(
            batch_results=[],
            context_map={},
            output_directory=None,
            agent_config=None
        )

        assert result == []

    def test_process_mixed_success_and_errors(self, processor, sample_agent_config):
        """Test pipeline with mix of successful and error results."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'},
            'rec_2': {'target_id': 'rec_2', 'source_guid': 'src_2', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(
                custom_id='rec_1',
                success=True,
                content={'result': 'success'},
                usage={},
                metadata={},
                error=None
            ),
            BatchResult(
                custom_id='rec_2',
                success=False,
                content=None,
                usage={},
                metadata={},
                error='Failed'
            )
        ]

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            agent_config=sample_agent_config
        )

        assert len(result) == 2
        # One success, one error
        success_items = [item for item in result if 'content' in item]
        error_items = [item for item in result if 'error' in item]
        assert len(success_items) == 1
        assert len(error_items) == 1
