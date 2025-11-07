"""
Parity tests for BatchResultProcessor.

These tests verify that the new BatchResultProcessor produces IDENTICAL output
to the legacy _convert_batch_results_to_workflow_format implementation.
"""
import pytest
from unittest.mock import patch
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.llm_invocation.realtime.providers.base import BatchResult


class TestBatchProcessorParity:
    """
    Parity tests comparing legacy vs new batch result processing.

    These tests run the same inputs through both implementations and verify
    identical output. This is critical for ensuring zero functional changes
    during refactoring.
    """

    def _compare_outputs(self, legacy_output, new_output):
        """
        Deep comparison of outputs, handling generated IDs.

        Generated values (node_id, target_id, lineage) are non-deterministic,
        so we verify structure rather than exact values.
        """
        assert len(legacy_output) == len(new_output), \
            f"Output length mismatch: legacy={len(legacy_output)}, new={len(new_output)}"

        for i, (legacy_item, new_item) in enumerate(zip(legacy_output, new_output)):
            # Check same keys (except for generated IDs which may vary slightly)
            legacy_keys = set(legacy_item.keys())
            new_keys = set(new_item.keys())
            assert legacy_keys == new_keys, \
                f"Item {i} key mismatch: legacy={legacy_keys}, new={new_keys}"

            for key in legacy_keys:
                legacy_val = legacy_item[key]
                new_val = new_item[key]

                # Special handling for generated fields
                if key == 'node_id':
                    # Both should have node_id with same prefix
                    if legacy_val and new_val:
                        assert legacy_val.split('_')[0] == new_val.split('_')[0]
                        assert legacy_val.split('_')[1] == new_val.split('_')[1]
                    else:
                        assert legacy_val == new_val

                elif key == 'lineage':
                    # Both should have same number of lineage entries
                    if legacy_val and new_val:
                        assert len(legacy_val) == len(new_val)
                        # Check structure matches (same prefixes)
                        for l_node, n_node in zip(legacy_val, new_val):
                            if '_' in str(l_node) and '_' in str(n_node):
                                assert l_node.split('_')[0] == n_node.split('_')[0]
                                assert l_node.split('_')[1] == n_node.split('_')[1]
                    else:
                        assert legacy_val == new_val

                elif key == 'target_id':
                    # If both generated, just verify both exist
                    # If from context, should be identical
                    if legacy_val and new_val:
                        # Both should exist
                        assert isinstance(legacy_val, str)
                        assert isinstance(new_val, str)
                    else:
                        assert legacy_val == new_val

                else:
                    # All other fields must be identical
                    assert legacy_val == new_val, \
                        f"Item {i} field '{key}' mismatch: legacy={legacy_val}, new={new_val}"

    def test_parity_basic_success(self):
        """Test parity for basic successful batch result."""
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

        agent_config = {'json_mode': True, 'schema': {'result': 'string'}}

        # Test legacy
        legacy_service = BatchService(use_batch_result_processor=False)
        legacy_output = legacy_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_1_TestAgent',
            agent_config=agent_config
        )

        # Test new
        new_service = BatchService(use_batch_result_processor=True)
        new_output = new_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_1_TestAgent',
            agent_config=agent_config
        )

        self._compare_outputs(legacy_output, new_output)

    def test_parity_multiple_items(self):
        """Test parity for multiple successful results."""
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

        agent_config = {'json_mode': True}

        legacy_service = BatchService(use_batch_result_processor=False)
        legacy_output = legacy_service._convert_batch_results_to_workflow_format(
            batch_results, context_map=context_map, agent_config=agent_config
        )

        new_service = BatchService(use_batch_result_processor=True)
        new_output = new_service._convert_batch_results_to_workflow_format(
            batch_results, context_map=context_map, agent_config=agent_config
        )

        self._compare_outputs(legacy_output, new_output)

    def test_parity_with_errors(self):
        """Test parity for error handling."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'},
            'rec_2': {'target_id': 'rec_2', 'source_guid': 'src_2', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(custom_id='rec_1', success=True, content={'result': 'success'}, usage={}, metadata={}, error=None),
            BatchResult(custom_id='rec_2', success=False, content=None, usage={}, metadata={}, error='Failed')
        ]

        agent_config = {'json_mode': True}

        legacy_service = BatchService(use_batch_result_processor=False)
        legacy_output = legacy_service._convert_batch_results_to_workflow_format(
            batch_results, context_map=context_map, agent_config=agent_config
        )

        new_service = BatchService(use_batch_result_processor=True)
        new_output = new_service._convert_batch_results_to_workflow_format(
            batch_results, context_map=context_map, agent_config=agent_config
        )

        self._compare_outputs(legacy_output, new_output)

    def test_parity_with_passthroughs(self):
        """Test parity for passthrough handling."""
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
            },
            'rec_3': {
                'target_id': 'rec_3',
                'source_guid': 'src_3',
                'content': 'data3',
                '_batch_filter_status': 'filtered'
            }
        }

        batch_results = [
            BatchResult(custom_id='rec_1', success=True, content={'result': 'processed'}, usage={}, metadata={}, error=None)
        ]

        agent_config = {'json_mode': True}

        legacy_service = BatchService(use_batch_result_processor=False)
        legacy_output = legacy_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_2_Agent',
            agent_config=agent_config
        )

        new_service = BatchService(use_batch_result_processor=True)
        new_output = new_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_2_Agent',
            agent_config=agent_config
        )

        self._compare_outputs(legacy_output, new_output)

    def test_parity_json_mode_false(self):
        """Test parity for json_mode=False."""
        context_map = {
            'rec_1': {'target_id': 'rec_1', 'source_guid': 'src_1', '_batch_filter_status': 'included'}
        }

        batch_results = [
            BatchResult(custom_id='rec_1', success=True, content='Plain text response', usage={}, metadata={}, error=None)
        ]

        agent_config = {'json_mode': False, 'output_field': 'text_content'}

        legacy_service = BatchService(use_batch_result_processor=False)
        legacy_output = legacy_service._convert_batch_results_to_workflow_format(
            batch_results, context_map=context_map, agent_config=agent_config
        )

        new_service = BatchService(use_batch_result_processor=True)
        new_output = new_service._convert_batch_results_to_workflow_format(
            batch_results, context_map=context_map, agent_config=agent_config
        )

        self._compare_outputs(legacy_output, new_output)

    def test_parity_complete_workflow(self):
        """Test parity for complete workflow with all features."""
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

        agent_config = {
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'json_mode': True,
            'schema': {'result': 'string'},
            'loop': {'iteration_id': 'iter_001'}
        }

        legacy_service = BatchService(use_batch_result_processor=False)
        legacy_service.context_map = context_map
        legacy_output = legacy_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_7_TestAgent',
            agent_config=agent_config
        )

        new_service = BatchService(use_batch_result_processor=True)
        new_service.context_map = context_map
        new_output = new_service._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory='/tmp/test/node_7_TestAgent',
            agent_config=agent_config
        )

        self._compare_outputs(legacy_output, new_output)
