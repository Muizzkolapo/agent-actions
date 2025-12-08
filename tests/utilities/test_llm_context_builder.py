"""
Unit tests for LLMContextBuilder.

Tests the centralized LLM context building logic shared between
batch and realtime modes.
"""

import pytest
from unittest.mock import patch, Mock
from agent_actions.utilities.context_scope.llm_context_builder import LLMContextBuilder


class TestLLMContextBuilderBatchMode:
    """Test suite for batch mode context building."""

    def test_build_llm_context_for_batch_basic_flow(self):
        """Test basic flow with observe and drop."""
        row_content = {'text': 'data', 'api_key': 'secret', 'id': '123'}
        llm_context = {'metadata': {'source': 'research'}}
        context_scope = {'drop': ['source.api_key']}

        result = LLMContextBuilder.build_llm_context_for_batch(
            row_content, llm_context, context_scope
        )

        # api_key should be removed
        assert 'api_key' not in result
        # Other original fields preserved
        assert result['text'] == 'data'
        assert result['id'] == '123'
        # Observed fields added
        assert result['metadata'] == {'source': 'research'}

    def test_build_llm_context_for_batch_no_drop(self):
        """Test with only observe fields (no drop directive)."""
        row_content = {'text': 'data', 'id': '123'}
        llm_context = {'metadata': {'source': 'research'}, 'entities': ['entity1']}
        context_scope = {}

        result = LLMContextBuilder.build_llm_context_for_batch(
            row_content, llm_context, context_scope
        )

        # Original fields preserved
        assert result['text'] == 'data'
        assert result['id'] == '123'
        # Observed fields added
        assert result['metadata'] == {'source': 'research'}
        assert result['entities'] == ['entity1']

    def test_build_llm_context_for_batch_no_observe(self):
        """Test with only drop directive (no observe fields)."""
        row_content = {'text': 'data', 'api_key': 'secret', 'password': 'secret2', 'id': '123'}
        llm_context = {}
        context_scope = {'drop': ['source.api_key', 'source.password']}

        result = LLMContextBuilder.build_llm_context_for_batch(
            row_content, llm_context, context_scope
        )

        # Both secrets dropped
        assert 'api_key' not in result
        assert 'password' not in result
        # Safe fields preserved
        assert result['text'] == 'data'
        assert result['id'] == '123'

    def test_build_llm_context_for_batch_empty_inputs(self):
        """Test with empty inputs."""
        result = LLMContextBuilder.build_llm_context_for_batch(
            {}, {}, None
        )

        assert result == {}

    def test_build_llm_context_for_batch_none_row_content(self):
        """Test with None as row_content."""
        llm_context = {'metadata': {'source': 'research'}}

        result = LLMContextBuilder.build_llm_context_for_batch(
            None, llm_context, None
        )

        # Should start with empty dict and add llm_context
        assert result == {'metadata': {'source': 'research'}}

    def test_build_llm_context_for_batch_non_dict_row_content(self):
        """Test with non-dict row_content."""
        row_content = "not a dict"
        llm_context = {'metadata': {'source': 'research'}}

        result = LLMContextBuilder.build_llm_context_for_batch(
            row_content, llm_context, None
        )

        # Should start with empty dict and add llm_context
        assert result == {'metadata': {'source': 'research'}}

    def test_build_llm_context_for_batch_invalid_field_reference(self):
        """Test that invalid field references are skipped silently."""
        row_content = {'text': 'data', 'id': '123'}
        llm_context = {}
        context_scope = {'drop': ['invalid_reference', 'no_dot_here']}

        # Should not raise error
        result = LLMContextBuilder.build_llm_context_for_batch(
            row_content, llm_context, context_scope
        )

        # Original data preserved (invalid refs skipped)
        assert result['text'] == 'data'
        assert result['id'] == '123'

    def test_build_llm_context_for_batch_drop_nonexistent_field(self):
        """Test dropping a field that doesn't exist in row_content."""
        row_content = {'text': 'data', 'id': '123'}
        llm_context = {}
        context_scope = {'drop': ['source.nonexistent_field']}

        result = LLMContextBuilder.build_llm_context_for_batch(
            row_content, llm_context, context_scope
        )

        # Should not error, original data preserved
        assert result['text'] == 'data'
        assert result['id'] == '123'

    def test_build_llm_context_for_batch_no_context_scope(self):
        """Test with context_scope=None."""
        row_content = {'text': 'data', 'api_key': 'secret'}
        llm_context = {'metadata': {'source': 'research'}}

        result = LLMContextBuilder.build_llm_context_for_batch(
            row_content, llm_context, None
        )

        # Nothing dropped (no context_scope)
        assert result['text'] == 'data'
        assert result['api_key'] == 'secret'
        # Observe fields added
        assert result['metadata'] == {'source': 'research'}

    def test_build_llm_context_for_batch_observe_overwrites(self):
        """Test that observe fields overwrite base fields with same key."""
        row_content = {'text': 'original', 'id': '123'}
        llm_context = {'text': 'observed'}  # Same key

        result = LLMContextBuilder.build_llm_context_for_batch(
            row_content, llm_context, None
        )

        # Observe field should overwrite
        assert result['text'] == 'observed'
        assert result['id'] == '123'


class TestLLMContextBuilderRealtimeMode:
    """Test suite for realtime mode context building."""

    def test_build_llm_context_for_realtime_basic_flow(self):
        """Test basic flow with observe and drop using DataTransformer."""
        processed_context = {'text': 'data', 'api_key': 'secret', 'id': '123'}
        llm_additional_context = {'metadata': {'source': 'research'}}
        context_scope = {'drop': ['source.api_key']}

        with patch('agent_actions.utilities.llm_context_builder.DataTransformer.remove_schema_objects') as mock_remove:
            # Mock DataTransformer to return context without api_key
            mock_remove.return_value = {'text': 'data', 'id': '123'}

            result = LLMContextBuilder.build_llm_context_for_realtime(
                processed_context, llm_additional_context, context_scope
            )

            # Verify DataTransformer was called with correct params
            mock_remove.assert_called_once_with(processed_context, ['api_key'])

            # Result should have dropped field removed and observe field added
            assert 'api_key' not in result
            assert result['text'] == 'data'
            assert result['id'] == '123'
            assert result['metadata'] == {'source': 'research'}

    def test_build_llm_context_for_realtime_no_drop(self):
        """Test with only observe fields (no drop directive)."""
        processed_context = {'text': 'data', 'id': '123'}
        llm_additional_context = {'metadata': {'source': 'research'}, 'entities': ['entity1']}
        context_scope = {}

        result = LLMContextBuilder.build_llm_context_for_realtime(
            processed_context, llm_additional_context, context_scope
        )

        # Original fields preserved
        assert result['text'] == 'data'
        assert result['id'] == '123'
        # Observed fields added
        assert result['metadata'] == {'source': 'research'}
        assert result['entities'] == ['entity1']

    def test_build_llm_context_for_realtime_no_observe(self):
        """Test with only drop directive (no observe fields)."""
        processed_context = {'text': 'data', 'api_key': 'secret', 'id': '123'}
        llm_additional_context = None
        context_scope = {'drop': ['source.api_key']}

        with patch('agent_actions.utilities.llm_context_builder.DataTransformer.remove_schema_objects') as mock_remove:
            mock_remove.return_value = {'text': 'data', 'id': '123'}

            result = LLMContextBuilder.build_llm_context_for_realtime(
                processed_context, llm_additional_context, context_scope
            )

            mock_remove.assert_called_once()
            assert 'api_key' not in result

    def test_build_llm_context_for_realtime_empty_inputs(self):
        """Test with empty inputs."""
        result = LLMContextBuilder.build_llm_context_for_realtime(
            {}, None, None
        )

        assert result == {}

    def test_build_llm_context_for_realtime_non_dict_processed_context(self):
        """Test with non-dict processed_context."""
        processed_context = "not a dict"
        llm_additional_context = {'metadata': {'source': 'research'}}

        result = LLMContextBuilder.build_llm_context_for_realtime(
            processed_context, llm_additional_context, None
        )

        # Should return unchanged
        assert result == "not a dict"

    def test_build_llm_context_for_realtime_invalid_field_reference(self):
        """Test that invalid field references are skipped silently."""
        processed_context = {'text': 'data', 'id': '123'}
        llm_additional_context = None
        context_scope = {'drop': ['invalid_reference', 'no_dot_here']}

        # Should not raise error, DataTransformer not called
        result = LLMContextBuilder.build_llm_context_for_realtime(
            processed_context, llm_additional_context, context_scope
        )

        # Original data preserved (no valid drop fields)
        assert result['text'] == 'data'
        assert result['id'] == '123'

    def test_build_llm_context_for_realtime_multiple_drops(self):
        """Test dropping multiple fields."""
        processed_context = {'text': 'data', 'api_key': 'secret1', 'password': 'secret2', 'id': '123'}
        llm_additional_context = None
        context_scope = {'drop': ['source.api_key', 'source.password']}

        with patch('agent_actions.utilities.llm_context_builder.DataTransformer.remove_schema_objects') as mock_remove:
            mock_remove.return_value = {'text': 'data', 'id': '123'}

            result = LLMContextBuilder.build_llm_context_for_realtime(
                processed_context, llm_additional_context, context_scope
            )

            # Verify DataTransformer called with both fields
            mock_remove.assert_called_once_with(processed_context, ['api_key', 'password'])

    def test_build_llm_context_for_realtime_no_context_scope(self):
        """Test with context_scope=None."""
        processed_context = {'text': 'data', 'api_key': 'secret'}
        llm_additional_context = {'metadata': {'source': 'research'}}

        result = LLMContextBuilder.build_llm_context_for_realtime(
            processed_context, llm_additional_context, None
        )

        # Nothing dropped (no context_scope)
        assert result['text'] == 'data'
        assert result['api_key'] == 'secret'
        # Observe fields added
        assert result['metadata'] == {'source': 'research'}

    def test_build_llm_context_for_realtime_observe_overwrites(self):
        """Test that observe fields overwrite base fields with same key."""
        processed_context = {'text': 'original', 'id': '123'}
        llm_additional_context = {'text': 'observed'}  # Same key

        result = LLMContextBuilder.build_llm_context_for_realtime(
            processed_context, llm_additional_context, None
        )

        # Observe field should overwrite
        assert result['text'] == 'observed'
        assert result['id'] == '123'

    def test_build_llm_context_for_realtime_datatransformer_not_called_if_no_drop_fields(self):
        """Test that DataTransformer is not called if drop list is empty after parsing."""
        processed_context = {'text': 'data', 'id': '123'}
        llm_additional_context = None
        context_scope = {'drop': ['invalid_ref']}  # Will be skipped

        with patch('agent_actions.utilities.llm_context_builder.DataTransformer.remove_schema_objects') as mock_remove:
            result = LLMContextBuilder.build_llm_context_for_realtime(
                processed_context, llm_additional_context, context_scope
            )

            # DataTransformer should NOT be called (drop_fields is empty)
            mock_remove.assert_not_called()
            assert result == processed_context
